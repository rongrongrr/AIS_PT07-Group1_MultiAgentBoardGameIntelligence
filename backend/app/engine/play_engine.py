"""Play Engine — orchestrates Playwright browser sessions for Azul games.

Each bot player gets its own independent browser session connecting to the same
room on buddyboardgames.com. The first bot creates the room, subsequent bots
join it. The host waits until all bots have joined, then starts the game.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from base64 import b64encode
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from app.azul.rules import is_game_over
from app.engine.action_executor import ExecutionResult, execute_action
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

_FRAME_LOG = os.environ.get("TILES_DEBUG_FRAMES")


class BotBrowser:
    """A single bot's Playwright browser session connected to an Azul room."""

    DEAL_COOLDOWN_S = 4.0
    JOIN_CONFIRM_TIMEOUT_S = 30.0

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
        # Latest state from the platform's WebSocket messages. Authoritative: preferred over
        # DOM scraping, which can lag animations and mislabel the other players.
        self.ws_state: Optional[GameStateData] = None
        self.round = 0
        self._last_deal_at = float("-inf")
        # names the platform has told us are in the room (host: every joiner; guest: everyone)
        self.lobby_players: set = set()
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
        await self._open_with_retries(url)
        await self._page.wait_for_timeout(1000)
        logger.info(f"[{self.player_name}] Browser launched")

    async def _open_with_retries(self, url: str, attempts: int = 3) -> None:
        """Load the game page. The site never reaches 'network idle' (ads, analytics), so wait
        for the DOM plus the room input, and retry transient load failures with backoff."""
        for attempt in range(1, attempts + 1):
            try:
                await self._page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                await self._page.wait_for_selector("#room", timeout=20_000)
                try:    # best effort: the site rarely goes fully idle, so do not fail on this
                    await self._page.wait_for_load_state("networkidle", timeout=8_000)
                except Exception:
                    pass
                return
            except Exception as e:
                if attempt == attempts:
                    raise
                logger.warning(f"[{self.player_name}] Page load attempt {attempt} failed ({e}); retrying")
                await asyncio.sleep(2 * attempt)

    async def _wait_in_lobby(self, timeout_s: float) -> bool:
        """True once the platform confirmed we are in a room (create/join response) or the
        lobby is visible on the page."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while True:
            if self.in_lobby:
                return True
            visible = await self._page.evaluate("""() => {
                const el = document.querySelector('#sharing-link-row');
                return !!(el && !el.classList.contains('d-none'));
            }""")
            if visible:
                self.in_lobby = True
                return True
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(0.25)

    async def join_room(self, attempts: int = 3):
        """Fill the room name and click Play, retrying until the platform confirms the room.

        Raises RuntimeError if it never does, so a session fails loudly instead of starting
        with fewer players than configured.
        """
        page = self._page
        if not page:
            raise RuntimeError("Browser not started")

        room_input = await page.wait_for_selector("#room", timeout=15000)
        await room_input.fill(self.room_name)
        await page.wait_for_timeout(300)
        play_btn = await page.wait_for_selector("#start-game", timeout=5000)
        await play_btn.click()

        # Several browsers starting at once can make the confirmation slow, so wait generously
        # and click again only if the page did not react (the button is still there).
        for attempt in range(1, attempts + 1):
            if await self._wait_in_lobby(self.JOIN_CONFIRM_TIMEOUT_S):
                break
            logger.warning(f"[{self.player_name}] Join attempt {attempt}/{attempts} not confirmed")
            if attempt < attempts and await page.is_visible("#start-game"):
                await (await page.wait_for_selector("#start-game", timeout=5000)).click()
        else:
            raise RuntimeError(f"[{self.player_name}] could not join room '{self.room_name}'")

        # Store room/player on window for the emit helper
        await page.evaluate(
            """([room, player]) => {
                window.__tiles_room = room;
                window.__tiles_player = player;
            }""",
            [self.room_name, self.player_name],
        )
        logger.info(f"[{self.player_name}] In lobby for room '{self.room_name}' (host={self.is_host})")

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

    async def deal_tiles(self, wait_s: float = 5.0):
        """Emit dealTiles and wait (up to ``wait_s``) for the platform to confirm the new round."""
        page = self._page
        if not page:
            return False
        self._last_deal_at = time.monotonic()
        self.arm_state_event()

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
            await self.wait_for_state_update(wait_s, clear=False)
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

    def arm_state_event(self) -> None:
        """Forget earlier updates; call just before acting so the reply cannot be missed."""
        self._state_event.clear()

    async def wait_for_state_update(self, timeout_s: float = 10, clear: bool = True) -> bool:
        """Wait until a new state arrives via WebSocket (``clear=False`` keeps an armed event)."""
        if clear:
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

    async def _board_is_empty(self) -> bool:
        """True if no real tiles are on any factory or in the center right now."""
        if not self._page:
            return False
        return await self._page.evaluate("""() => {
            const real = (sel) => Array.from(document.querySelectorAll(sel))
                .filter(t => t.getAttribute('tilecolor') !== 'dummy');
            return real('.factory .tile[tilecolor]').length === 0
                && real('#center-row .tile[tilecolor]').length === 0;
        }""") or False

    async def needs_deal(self, settle_ms: int = 700) -> bool:
        """True if all factories and the center are empty (a new round must be dealt).

        The board is briefly empty while tiles animate between rounds, and dealing
        then makes the platform reject the request, so the empty reading must hold
        for ``settle_ms`` and no game-over signal may be present.
        """
        if self.game_over:
            return False
        if time.monotonic() - self._last_deal_at < self.DEAL_COOLDOWN_S:
            return False                            # the page also auto-deals; avoid duplicate requests
        ws = self.ws_state
        if ws is not None and ws.round_in_progress is True:
            return False
        if ws is not None and ws.game_over:
            return False
        if not await self._board_is_empty():
            return False                            # also guards against a stale round-over state
        await asyncio.sleep(settle_ms / 1000)
        if not await self._board_is_empty():
            return False
        return not await self.check_game_over()

    async def _read_game_over_signals(self) -> dict:
        """Raw page signals. ``strong`` are only shown at a real game end; ``weak`` are
        text matches that can also appear in transient error messages."""
        return await self._page.evaluate("""() => {
            const visible = (el) => !!el && el.offsetHeight > 0 && el.offsetWidth > 0;
            const text = document.body.innerText;
            return {
                strong: visible(document.querySelector('.rematch-button'))
                     || visible(document.querySelector('.pyro')),
                weak: text.includes('wins!')
                     || text.includes('no more turns remaining')
                     || text.includes('There are no more turns'),
            };
        }""") or {"strong": False, "weak": False}

    async def check_game_over(self) -> bool:
        """Has the game ended?

        Accepted evidence, in order:
        1. The server said so (``gameOver`` in a takeTurnResponse) - sets ``self.game_over``.
        2. The rematch button or fireworks are visible.
        3. A text signal ("wins!", "no more turns remaining") *and* a completed wall row
           on the board. Text alone is not trusted: error toasts can contain it, and
           acting on it would end a game in round 1 or 2.
        """
        if self.game_over:
            return True
        if self.ws_state is not None and self.ws_state.game_over:
            self.game_over = True
            return True
        if not self._page:
            return False
        sig = await self._read_game_over_signals()
        if sig.get("strong"):
            self.game_over = True
            return True
        if sig.get("weak"):
            state = await parse_state_from_dom(self._page)
            if state is not None and is_game_over(state):
                self.game_over = True
                return True
            logger.warning(f"[{self.player_name}] Game-over text seen but no completed wall row; ignoring")
        return False

    async def get_player_index(self) -> int:
        """Get this bot's player index from the current state or DOM."""
        if self.current_state:
            for p in self.current_state.players:
                if p.name == self.player_name:
                    return p.index
        return 0

    async def refresh_state_from_dom(self) -> Optional[GameStateData]:
        """Fallback: parse game state from the DOM."""
        if self.ws_state is not None:
            return self.ws_state
        if not self._page:
            return None
        state = await parse_state_from_dom(self._page)
        if state:
            state.session_id = self.session_id
            state.room_name = self.room_name
            self.current_state = state
        return state

    async def execute_move(self, action: GameAction):
        """Execute an action on the web UI. Returns an ExecutionResult (truthy on success)."""
        if not self._page:
            return ExecutionResult(False)
        player_index = await self.get_player_index()
        return await execute_action(self._page, action, player_index)

    async def get_scores(self) -> Dict[str, int]:
        """Current scores: from the platform's state when available, else the DOM."""
        if self.ws_state is not None:
            return {p.name: p.score for p in self.ws_state.players}
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

    def _log_frame(self, payload, direction: str) -> None:
        """Debug aid: append every frame to $TILES_DEBUG_FRAMES (one JSON line each)."""
        try:
            with open(_FRAME_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"player": self.player_name, "dir": direction,
                                    "frame": payload if isinstance(payload, str) else repr(payload)}) + "\n")
        except OSError:
            pass

    def _handle_websocket(self, ws):
        ws.on("framereceived", lambda payload: self._on_ws_frame(payload, "received"))
        ws.on("framesent", lambda payload: self._on_ws_frame(payload, "sent"))

    def _on_ws_frame(self, payload: str, direction: str):
        if _FRAME_LOG:
            self._log_frame(payload, direction)
        parsed = parse_socketio_message(payload)
        if not parsed:
            return

        event_name, event_data = parsed

        if direction != "received":
            return

        if event_name == "takeTurnResponse":
            state = parse_game_state_from_event(event_data, self.session_id)
            if state:
                if event_data.get("turnType") == "dealTiles" and event_data.get("success"):
                    self.round += 1
                state.round = max(self.round, 1)
                self.ws_state = state
                self.current_state = state
                self.game_started = True
                if state.game_over:
                    self.game_over = True
                if event_data.get("success"):      # only accepted turns confirm a move/deal
                    self._state_event.set()

        elif event_name == "startGameResponse":
            state = parse_start_game_response(
                event_data, self.room_name, self.session_id
            )
            if state:
                self.current_state = state
                self.game_started = True
                self._state_event.set()

        elif event_name in ("joinRoomResponse", "createRoomResponse"):
            if event_data.get("success"):
                self.in_lobby = True
                self.lobby_players.update(event_data.get("players") or [])
                if event_name == "createRoomResponse":
                    self.lobby_players.add(self.player_name)


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

    @property
    def expected_players(self) -> int:
        return len(self.bots) + self.human_count

    async def wait_for_all_players(self, timeout_s: float) -> bool:
        """Wait until the host has been told the whole expected roster is in the room."""
        host = self.host
        if not host:
            return False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_s
        while len(host.lobby_players) < self.expected_players:
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(0.5)
        return True

    async def wait_for_humans(self, timeout_s: int = 300):
        """Wait for human players to join (the platform reports each join to the host)."""
        if self.human_count <= 0:
            return
        logger.info(f"Waiting for {self.human_count} human(s) to join ({self.expected_players} total)...")
        if await self.wait_for_all_players(timeout_s):
            logger.info(f"All {self.expected_players} players in lobby")
        else:
            logger.warning("Timed out waiting for human players")

    async def start_game(self, join_timeout_s: float = 30):
        """Host starts the game, but only once every expected player is in the room (the
        platform enables Start with a single player, so the button state proves nothing)."""
        host = self.host
        if not host:
            return
        if not await self.wait_for_all_players(join_timeout_s):
            raise RuntimeError(
                f"Only {len(host.lobby_players)} of {self.expected_players} players are in the room"
            )
        await host.start_game()
        # Wait for all bots to receive the startGameResponse
        await asyncio.sleep(2)

    async def close_all(self):
        """Close all bot browsers."""
        await asyncio.gather(*(bot.close() for bot in self.bots), return_exceptions=True)
