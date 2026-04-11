"""Play Engine — orchestrates Playwright browser sessions for Azul games.

Each bot player gets its own independent browser session connecting to the same
room on buddyboardgames.com. The first bot creates the room, subsequent bots
join it. The host waits until all bots have joined, then starts the game.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from base64 import b64encode
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from app.engine.action_executor import execute_action
from app.engine.state_parser import (
    parse_game_state_from_event,
    parse_socketio_message,
    parse_start_game_response,
    parse_state_from_dom,
)
from app.models.schemas import (
    BrowserMode,
    GameAction,
    GameStateData,
    MoveRecord,
    SessionStatus,
)

logger = logging.getLogger(__name__)


class BotBrowser:
    """A single bot's Playwright browser session connected to an Azul room."""

    def __init__(
        self,
        session_id: str,
        room_name: str,
        player_name: str,
        platform_url: str = "https://buddyboardgames.com/azul",
        browser_mode: BrowserMode = BrowserMode.HEADLESS,
        is_host: bool = False,
    ):
        self.session_id = session_id
        self.room_name = room_name
        self.player_name = player_name
        self.platform_url = platform_url
        self.browser_mode = browser_mode
        self.is_host = is_host

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

        self.current_state: Optional[GameStateData] = None
        self.in_lobby = False
        self.game_started = False
        self.game_over = False
        self._state_event = asyncio.Event()
        self._ws_messages: List[Dict[str, Any]] = []

    @property
    def page(self) -> Optional[Page]:
        return self._page

    async def launch(self):
        """Launch browser and navigate to the game page."""
        self._playwright = await async_playwright().start()
        headless = self.browser_mode == BrowserMode.HEADLESS
        self._browser = await self._playwright.chromium.launch(headless=headless)
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 900}
        )
        self._page = await self._context.new_page()
        self._page.on("websocket", self._handle_websocket)

        # Inject script to capture the Socket.IO socket reference onto window.__socket
        # This runs before any page JS, intercepting io.connect() calls.
        await self._page.add_init_script("""
            (function() {
                // Wait for io to be defined, then monkey-patch io.connect
                const origDefineProperty = Object.defineProperty;
                let _io = undefined;

                // Intercept when 'io' is assigned to window
                try {
                    origDefineProperty(window, 'io', {
                        configurable: true,
                        get: function() { return _io; },
                        set: function(val) {
                            _io = val;
                            if (val && typeof val.connect === 'function') {
                                const origConnect = val.connect.bind(val);
                                val.connect = function() {
                                    const socket = origConnect.apply(val, arguments);
                                    window.__tiles_socket = socket;
                                    return socket;
                                };
                            }
                            // Also patch the callable form: io(url)
                            // io itself might be a function
                        }
                    });
                } catch(e) {
                    // Fallback: poll for socket
                }
            })();
        """)

        name_b64 = b64encode(self.player_name.encode()).decode()
        url = f"{self.platform_url}?name={name_b64}"
        logger.info(f"[{self.player_name}] Navigating to {url}")
        await self._page.goto(url, wait_until="networkidle")
        await self._page.wait_for_timeout(1000)
        logger.info(f"[{self.player_name}] Browser launched")

    async def join_room(self):
        """Fill room name and click Play to join/create the room."""
        page = self._page
        if not page:
            raise RuntimeError("Browser not started")

        room_input = await page.wait_for_selector("#room", timeout=5000)
        await room_input.fill(self.room_name)
        await page.wait_for_timeout(300)

        play_btn = await page.wait_for_selector("#start-game", timeout=5000)
        await play_btn.click()
        await page.wait_for_timeout(2500)

        # Verify lobby state
        self.in_lobby = await page.evaluate("""() => {
            const el = document.querySelector('#sharing-link-row');
            return !!(el && !el.classList.contains('d-none'));
        }""") or False

        # Store room/player on window for the emit helper
        await page.evaluate(
            """([room, player]) => {
                window.__tiles_room = room;
                window.__tiles_player = player;
            }""",
            [self.room_name, self.player_name],
        )

        if self.in_lobby:
            logger.info(f"[{self.player_name}] In lobby for room '{self.room_name}' (host={self.is_host})")
        else:
            logger.warning(f"[{self.player_name}] May not have joined room")
            self.in_lobby = True  # optimistic

    async def start_game(self):
        """Click Start Game button (host only). Waits until button is enabled."""
        if not self.is_host:
            return
        page = self._page
        if not page:
            return

        # Wait for the start button to become enabled (all players joined)
        for _ in range(30):  # up to 30 seconds
            btn = await page.query_selector("#start-game-lobby")
            if btn:
                disabled = await btn.get_attribute("disabled")
                if not disabled:
                    await btn.click()
                    logger.info(f"[{self.player_name}] Clicked Start Game")
                    await page.wait_for_timeout(2000)
                    return
            await page.wait_for_timeout(1000)

        logger.error(f"[{self.player_name}] Start button never became enabled")

    async def deal_tiles(self):
        """Emit dealTiles event. Only the current turn player should call this."""
        page = self._page
        if not page:
            return False

        result = await page.evaluate(
            """([room, player]) => {
                // Try multiple ways to find the socket
                const socket = window.__tiles_socket || window.socket;
                if (socket && typeof socket.emit === 'function') {
                    socket.emit('takeTurn', {
                        room: room,
                        player: player,
                        gameName: 'azul',
                        turnType: 'dealTiles'
                    });
                    return 'socket';
                }
                return false;
            }""",
            [self.room_name, self.player_name],
        )

        if result:
            logger.info(f"[{self.player_name}] Emitted dealTiles via {result}")
            await page.wait_for_timeout(1500)
            return True

        # Fallback: emit dealTiles via raw WebSocket frame
        logger.warning(f"[{self.player_name}] No socket found, trying raw WS emit")
        try:
            import json as _json
            msg = _json.dumps(["takeTurn", {
                "room": self.room_name,
                "player": self.player_name,
                "gameName": "azul",
                "turnType": "dealTiles",
            }])
            raw = f"42{msg}"
            await page.evaluate(
                """(raw) => {
                    // Find the active WebSocket
                    const perf = performance.getEntriesByType('resource')
                        .filter(r => r.name.includes('socket.io'));
                    // Try to send via any open WebSocket
                    if (window.__tiles_ws) {
                        window.__tiles_ws.send(raw);
                        return true;
                    }
                    return false;
                }""",
                raw,
            )
            await page.wait_for_timeout(1500)
        except Exception as e:
            logger.error(f"[{self.player_name}] Raw WS fallback failed: {e}")

        return False

    async def wait_for_state_update(self, timeout_s: float = 10) -> bool:
        """Wait until a new state arrives via WebSocket."""
        self._state_event.clear()
        try:
            await asyncio.wait_for(self._state_event.wait(), timeout=timeout_s)
            return True
        except asyncio.TimeoutError:
            return False

    async def is_my_turn(self) -> bool:
        """Check if it's this bot's turn.

        Primary: use the WebSocket game state (currentPlayer field).
        Fallback: use DOM prompt text.
        """
        # Check from WebSocket state first — most reliable
        if self.current_state and self.current_state.current_turn:
            return self.current_state.current_turn == self.player_name

        # Fallback: check DOM
        if not self._page:
            return False
        return await self._page.evaluate("""(myName) => {
            const lobby = document.querySelector('#sharing-link-row');
            if (lobby && !lobby.classList.contains('d-none')) return false;
            const modal = document.querySelector('#new-game-modal');
            if (modal && modal.classList.contains('show')) return false;

            // Check prompt text
            const text = document.body.innerText;
            if (text.includes('Select a tile to claim')) return true;
            if (text.includes('Select a row')) return true;
            if (text.includes('Waiting for')) return false;

            // CSS class fallback
            const meInfo = document.querySelector('#me-info');
            return !!(meInfo && meInfo.classList.contains('current-turn'));
        }""", self.player_name) or False

    async def needs_deal(self) -> bool:
        """Check if all factories and center are empty (need to deal tiles for new round)."""
        if not self._page:
            return False
        return await self._page.evaluate("""() => {
            // Count actual game tiles (not demo tiles)
            // After game starts, factory tiles have a factoryid attribute
            const factoryTiles = document.querySelectorAll('.factory .tile[tilecolor]');
            const realFactoryTiles = Array.from(factoryTiles).filter(
                t => t.getAttribute('tilecolor') !== 'dummy'
            );
            const centerTiles = document.querySelectorAll('#center-row .tile[tilecolor]');
            const realCenterTiles = Array.from(centerTiles).filter(
                t => t.getAttribute('tilecolor') !== 'dummy'
            );
            return realFactoryTiles.length === 0 && realCenterTiles.length === 0;
        }""") or False

    async def check_game_over(self) -> bool:
        """Check if the game has ended.

        Checks multiple signals:
        1. Rematch button rendered with actual height
        2. Fireworks animation visible
        3. "wins!" text in the page
        4. "no more turns remaining" error message
        """
        if self.game_over:
            return True
        if not self._page:
            return False
        result = await self._page.evaluate("""() => {
            // Rematch button rendered
            const rematch = document.querySelector('.rematch-button');
            if (rematch && rematch.offsetHeight > 0 && rematch.offsetWidth > 0) return true;

            // Fireworks
            const pyro = document.querySelector('.pyro');
            if (pyro && pyro.offsetHeight > 0) return true;

            // Win text
            const text = document.body.innerText;
            if (text.includes('wins!')) return true;

            // "no more turns" error
            if (text.includes('no more turns remaining')) return true;
            if (text.includes('There are no more turns')) return true;

            return false;
        }""") or False
        if result:
            self.game_over = True
        return result

    async def get_player_index(self) -> int:
        """Get this bot's player index from the current state or DOM."""
        if self.current_state:
            for p in self.current_state.players:
                if p.name == self.player_name:
                    return p.index
        return 0

    async def refresh_state_from_dom(self) -> Optional[GameStateData]:
        """Fallback: parse game state from the DOM."""
        if not self._page:
            return None
        state = await parse_state_from_dom(self._page)
        if state:
            state.session_id = self.session_id
            state.room_name = self.room_name
            self.current_state = state
        return state

    async def execute_move(self, action: GameAction) -> bool:
        """Execute an action on the web UI."""
        if not self._page:
            return False
        player_index = await self.get_player_index()
        return await execute_action(self._page, action, player_index)

    async def get_scores(self) -> Dict[str, int]:
        """Get current scores from DOM."""
        if not self._page:
            return {}
        return await self._page.evaluate("""() => {
            const scores = {};
            for (let i = 0; i < 4; i++) {
                const el = document.querySelector(`#player-${i}-score`);
                if (!el) break;
                const nameEl = i === 0
                    ? document.querySelector('#me-info-name')
                    : document.querySelectorAll('.other-player-info-text b')[i-1];
                const name = nameEl ? nameEl.textContent.trim() : `Player_${i}`;
                scores[name] = parseInt(el.textContent) || 0;
            }
            return scores;
        }""") or {}

    async def close(self):
        """Clean up all browser resources."""
        try:
            if self._page:
                await self._page.close()
            if self._context:
                await self._context.close()
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.warning(f"[{self.player_name}] Close error: {e}")
        logger.info(f"[{self.player_name}] Browser closed")

    # --- WebSocket interception ---

    def _handle_websocket(self, ws):
        ws.on("framereceived", lambda payload: self._on_ws_frame(payload, "received"))
        ws.on("framesent", lambda payload: self._on_ws_frame(payload, "sent"))

    def _on_ws_frame(self, payload: str, direction: str):
        parsed = parse_socketio_message(payload)
        if not parsed:
            return

        event_name, event_data = parsed

        if direction != "received":
            return

        if event_name == "takeTurnResponse":
            state = parse_game_state_from_event(event_data, self.session_id)
            if state:
                self.current_state = state
                self.game_started = True
                if state.game_over:
                    self.game_over = True
                self._state_event.set()

        elif event_name == "startGameResponse":
            state = parse_start_game_response(
                event_data, self.room_name, self.session_id
            )
            if state:
                self.current_state = state
                self.game_started = True
                self._state_event.set()

        elif event_name == "joinRoomResponse":
            if event_data.get("success"):
                self.in_lobby = True


class MultiPlayerSession:
    """Manages multiple BotBrowser instances all playing in the same Azul room."""

    def __init__(
        self,
        session_id: str,
        room_name: str,
        platform_url: str,
        browser_mode: BrowserMode,
    ):
        self.session_id = session_id
        self.room_name = room_name
        self.platform_url = platform_url
        self.browser_mode = browser_mode
        self.bots: List[BotBrowser] = []
        self.human_count: int = 0  # how many human slots we're waiting for

    def add_bot(self, player_name: str, is_host: bool = False) -> BotBrowser:
        bot = BotBrowser(
            session_id=self.session_id,
            room_name=self.room_name,
            player_name=player_name,
            platform_url=self.platform_url,
            browser_mode=self.browser_mode,
            is_host=is_host,
        )
        self.bots.append(bot)
        return bot

    @property
    def host(self) -> Optional[BotBrowser]:
        for bot in self.bots:
            if bot.is_host:
                return bot
        return self.bots[0] if self.bots else None

    async def launch_all(self):
        """Launch all bot browsers in parallel."""
        await asyncio.gather(*(bot.launch() for bot in self.bots))

    async def join_all(self):
        """Join room sequentially: host first to create room, then others."""
        host = self.host
        if host:
            await host.join_room()
            await asyncio.sleep(1)

        others = [b for b in self.bots if b is not host]
        for bot in others:
            await bot.join_room()
            await asyncio.sleep(0.5)

    async def wait_for_humans(self, timeout_s: int = 300):
        """Wait for human players to join (poll lobby player count).

        The host's page shows the player count. We wait until total players
        (bots + humans) match the expected count.
        """
        if self.human_count <= 0:
            return

        host = self.host
        if not host or not host.page:
            return

        expected_total = len(self.bots) + self.human_count
        logger.info(f"Waiting for {self.human_count} human(s) to join ({expected_total} total)...")

        start = time.time()
        while time.time() - start < timeout_s:
            player_count = await host.page.evaluate("""() => {
                const players = document.querySelectorAll('.lobby-ribbon-row .player-name, #sharing-link-row .badge');
                // Fallback: count buddy avatars in the lobby
                const avatars = document.querySelectorAll('.buddy-avatar');
                return Math.max(players.length, avatars.length);
            }""") or len(self.bots)

            if player_count >= expected_total:
                logger.info(f"All {expected_total} players in lobby")
                return

            await asyncio.sleep(2)

        logger.warning(f"Timeout waiting for humans, proceeding with {len(self.bots)} bot(s)")

    async def start_game(self):
        """Host starts the game."""
        host = self.host
        if host:
            await host.start_game()
            # Wait for all bots to receive the startGameResponse
            await asyncio.sleep(2)

    async def close_all(self):
        """Close all bot browsers."""
        await asyncio.gather(*(bot.close() for bot in self.bots), return_exceptions=True)
