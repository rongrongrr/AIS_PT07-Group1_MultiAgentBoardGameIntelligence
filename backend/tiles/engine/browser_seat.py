"""One player seat on the live platform = one Chromium browser.

Ported from the Milestone-1 ``BotBrowser`` with the same validated
mechanics (init-script socket capture, WS frame interception, emit with
server ack) but slimmed to a pure transport: this class knows nothing
about strategies or rules — it surfaces the site's authoritative game
object and emits payloads it is handed.
"""

from __future__ import annotations

import asyncio
import logging
from base64 import b64encode
from typing import Any, Dict, Optional

from . import protocol
from .protocol import (
    EV_JOIN_ROOM_RESPONSE,
    EV_START_GAME_RESPONSE,
    EV_TAKE_TURN_RESPONSE,
    parse_socketio_frame,
)

logger = logging.getLogger(__name__)

_PLAYWRIGHT_HINT = (
    "Playwright is required for live play. Install with:\n"
    "  pip install 'tiles[live]' && playwright install chromium"
)

# Injected before any page JS: intercepts the assignment of `io` so we
# can wrap io.connect and stash the live socket on window.__tiles_socket.
_SOCKET_CAPTURE_SCRIPT = """
(function() {
    let _io = undefined;
    try {
        Object.defineProperty(window, 'io', {
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
            }
        });
    } catch (e) { /* fall back to WS-frame interception only */ }
})();
"""

# Emit takeTurn and await the server's takeTurnResponse ack (5s timeout).
# prependOnceListener keeps the site's own handlers working.
_EMIT_AND_WAIT_JS = """
(payload) => {
    return new Promise((resolve) => {
        const socket = window.__tiles_socket;
        if (!socket) { resolve({ok: false, msg: 'no_socket'}); return; }
        const room = window.__tiles_room || '';
        const player = window.__tiles_player || '';
        if (!room || !player) {
            resolve({ok: false, msg: 'no room/player bound'});
            return;
        }
        payload.room = room;
        payload.player = player;
        payload.gameName = 'azul';

        let resolved = false;
        const handler = (resp) => {
            if (!resolved) {
                resolved = true;
                socket.off('takeTurnResponse', handler);
                resolve({ok: !!resp.success, msg: resp.message || ''});
            }
        };
        socket.prependOnceListener
            ? socket.prependOnceListener('takeTurnResponse', handler)
            : socket.once('takeTurnResponse', handler);
        socket.emit('takeTurn', payload);
        setTimeout(() => {
            if (!resolved) {
                resolved = true;
                socket.off('takeTurnResponse', handler);
                resolve({ok: false, msg: 'ack timeout (5s)'});
            }
        }, 5000);
    });
}
"""

_GAME_OVER_JS = """
() => {
    const rematch = document.querySelector('.rematch-button');
    if (rematch && rematch.offsetHeight > 0 && rematch.offsetWidth > 0) return true;
    const pyro = document.querySelector('.pyro');
    if (pyro && pyro.offsetHeight > 0) return true;
    const text = document.body.innerText;
    if (text.includes('wins!')) return true;
    if (text.includes('no more turns remaining')) return true;
    if (text.includes('There are no more turns')) return true;
    return false;
}
"""

_NEEDS_DEAL_JS = """
() => {
    const real = (sel) => Array.from(document.querySelectorAll(sel))
        .filter(t => t.getAttribute('tilecolor') !== 'dummy').length;
    return real('.factory .tile[tilecolor]') === 0
        && real('#center-row .tile[tilecolor]') === 0;
}
"""


class BrowserSeat:
    """Async Playwright wrapper for one bot's seat in a live room."""

    def __init__(
        self,
        room_name: str,
        player_name: str,
        platform_url: str = protocol.DEFAULT_PLATFORM_URL,
        headless: bool = True,
        is_host: bool = False,
    ) -> None:
        self.room_name = room_name
        self.player_name = player_name
        self.platform_url = platform_url
        self.headless = headless
        self.is_host = is_host

        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

        #: latest authoritative game object from a takeTurnResponse
        self.site_game: Optional[Dict[str, Any]] = None
        self.in_lobby = False
        self.game_started = False
        self.game_over = False
        self._state_event = asyncio.Event()

    # -- lifecycle ------------------------------------------------------------

    async def launch(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:  # pragma: no cover
            raise ImportError(_PLAYWRIGHT_HINT) from exc

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless
        )
        self._context = await self._browser.new_context(
            viewport={"width": 1280, "height": 900}
        )
        self._page = await self._context.new_page()
        self._page.on("websocket", self._handle_websocket)
        await self._page.add_init_script(_SOCKET_CAPTURE_SCRIPT)

        name_b64 = b64encode(self.player_name.encode()).decode()
        url = f"{self.platform_url}?name={name_b64}"
        logger.info("[%s] navigating to %s", self.player_name, url)
        await self._page.goto(url, wait_until="networkidle")
        await self._page.wait_for_timeout(1000)

    async def join_room(self) -> None:
        """Fill the room name and click Play (creates the room for the
        first joiner, joins otherwise — the site decides)."""
        page = self._require_page()
        room_input = await page.wait_for_selector(
            protocol.SEL_ROOM_INPUT, timeout=10000
        )
        await room_input.fill(self.room_name)
        await page.wait_for_timeout(300)
        play = await page.wait_for_selector(
            protocol.SEL_PLAY_BUTTON, timeout=10000
        )
        await play.click()
        await page.wait_for_timeout(2500)

        self.in_lobby = bool(
            await page.evaluate(
                f"""() => {{
                    const el = document.querySelector('{protocol.SEL_LOBBY_ROW}');
                    return !!(el && !el.classList.contains('d-none'));
                }}"""
            )
        )
        # Bind room/player for the emit helper.
        await page.evaluate(
            """([room, player]) => {
                window.__tiles_room = room;
                window.__tiles_player = player;
            }""",
            [self.room_name, self.player_name],
        )
        if not self.in_lobby:
            logger.warning(
                "[%s] lobby indicator not found; proceeding optimistically",
                self.player_name,
            )
            self.in_lobby = True

    async def start_game(self, timeout_s: float = 30) -> bool:
        """Host only: click Start Game once the button enables (all
        players present)."""
        if not self.is_host:
            return False
        page = self._require_page()
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            btn = await page.query_selector(protocol.SEL_START_LOBBY)
            if btn and not await btn.get_attribute("disabled"):
                await btn.click()
                logger.info("[%s] clicked Start Game", self.player_name)
                await page.wait_for_timeout(2000)
                return True
            await page.wait_for_timeout(1000)
        logger.error("[%s] start button never enabled", self.player_name)
        return False

    async def close(self) -> None:
        for closer in (self._page, self._context, self._browser):
            try:
                if closer:
                    await closer.close()
            except Exception:  # noqa: BLE001 — best-effort teardown
                pass
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception:  # noqa: BLE001
            pass
        logger.info("[%s] browser closed", self.player_name)

    # -- state ----------------------------------------------------------------

    async def wait_for_state(self, timeout_s: float = 10) -> bool:
        """Wait for the next authoritative state via WS interception."""
        self._state_event.clear()
        try:
            await asyncio.wait_for(self._state_event.wait(), timeout=timeout_s)
            return True
        except asyncio.TimeoutError:
            return False

    def is_my_turn(self) -> bool:
        return bool(
            self.site_game
            and self.site_game.get("currentPlayer") == self.player_name
        )

    async def needs_deal(self) -> bool:
        """All factories and the center empty on screen — the current
        player must emit dealTiles to start the next round."""
        page = self._require_page()
        return bool(await page.evaluate(_NEEDS_DEAL_JS))

    async def check_game_over(self) -> bool:
        if self.game_over:
            return True
        page = self._require_page()
        if await page.evaluate(_GAME_OVER_JS):
            self.game_over = True
        return self.game_over

    # -- actions --------------------------------------------------------------

    async def _emit(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        page = self._require_page()
        return await page.evaluate(_EMIT_AND_WAIT_JS, dict(payload))

    async def emit_action(
        self, choose: Dict[str, Any], place: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Two-step move with server acks. On a rejected placement,
        fall back to the floor so the seat never wedges the room (the
        local validator makes rejections rare; this guards against
        state drift). Returns {'ok': bool, 'msg': str, 'fallback': bool}.
        """
        page = self._require_page()
        result = await self._emit(choose)
        if not result.get("ok"):
            return {"ok": False, "msg": f"chooseTiles: {result.get('msg')}",
                    "fallback": False}
        await page.wait_for_timeout(300)

        result = await self._emit(place)
        if result.get("ok"):
            await page.wait_for_timeout(500)
            return {"ok": True, "msg": "", "fallback": False}

        logger.warning(
            "[%s] placeTiles rejected (%s); floor fallback",
            self.player_name,
            result.get("msg"),
        )
        result = await self._emit(protocol.place_tiles_payload(None))
        await page.wait_for_timeout(500)
        return {
            "ok": bool(result.get("ok")),
            "msg": result.get("msg", ""),
            "fallback": True,
        }

    async def deal_tiles(self) -> bool:
        result = await self._emit(protocol.deal_tiles_payload())
        page = self._require_page()
        await page.wait_for_timeout(1000)
        return bool(result.get("ok"))

    # -- internals -------------------------------------------------------------

    def _require_page(self):
        if self._page is None:
            raise RuntimeError(
                f"seat {self.player_name} not launched; call launch() first"
            )
        return self._page

    def _handle_websocket(self, ws) -> None:
        ws.on(
            "framereceived",
            lambda payload: self._on_frame(payload),
        )

    def _on_frame(self, payload: str) -> None:
        parsed = parse_socketio_frame(payload)
        if not parsed:
            return
        event, data = parsed
        if event == EV_TAKE_TURN_RESPONSE:
            if isinstance(data, dict) and data.get("success") and data.get("game"):
                self.site_game = data["game"]
                self.game_started = True
                if data["game"].get("gameOver"):
                    self.game_over = True
                self._state_event.set()
        elif event == EV_START_GAME_RESPONSE:
            if isinstance(data, dict) and data.get("success"):
                self.game_started = True
                self._state_event.set()
        elif event == EV_JOIN_ROOM_RESPONSE:
            if isinstance(data, dict) and data.get("success"):
                self.in_lobby = True
