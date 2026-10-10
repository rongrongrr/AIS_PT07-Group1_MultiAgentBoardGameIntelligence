"""One player seat on the live platform = one Chromium browser.

A pure transport: this class knows nothing about strategies or rules —
it drives the site's lobby UI, surfaces the authoritative game object
from the site's WebSocket, and sends payloads it is handed through that
same socket (so the site's own client stays in sync and renders the
board for a headed demo).

Mechanics (verified live, October 2026; see ``protocol.py``):

* an init script wraps ``window.WebSocket`` so the page's socket is
  reachable as ``window.__tiles_ws``;
* Playwright's WebSocket frame interception feeds every server frame
  through ``protocol.parse_frame``: lobby membership, seat order
  (``startGameResponse``), the authoritative ``game`` (every
  ``takeTurnResponse``), and round boundaries (``dealTiles`` responses);
* a move is ``ws.send(JSON)`` plus a one-off message listener that
  resolves on the next ``takeTurnResponse`` (5 s timeout).

Seat interface (what ``LiveSession`` relies on; the offline test harness
implements the same surface without a browser):

    launch(), join_room(), start_game() -> bool, close()
    site_game, site_players, lobby_players, state_seq, rounds_dealt,
    game_over, is_host, player_name
    wait_for_state(timeout_s, since=None) -> bool
    needs_deal() -> bool, check_game_over() -> bool
    lobby_player_count() -> int
    emit_action(choose, place) -> {"ok", "msg", "fallback"}
    deal_tiles() -> bool
    dom_snapshot() -> site-like game dict | None
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from . import protocol
from .dom_snapshot import DOM_SNAPSHOT_JS, snapshot_to_site_game
from .protocol import (
    EV_CREATE_ROOM_RESPONSE,
    EV_END_GAME_RESPONSE,
    EV_JOIN_ROOM_RESPONSE,
    EV_START_GAME_RESPONSE,
    EV_TAKE_TURN_RESPONSE,
    parse_frame,
)

logger = logging.getLogger(__name__)

_PLAYWRIGHT_HINT = (
    "Playwright is required for live play. Install with:\n"
    "  pip install 'tiles[live]' && playwright install chromium"
)

# Injected before any page JS: wrap the WebSocket constructor so the
# page's live socket is reachable from page.evaluate().
_WS_CAPTURE_SCRIPT = """
(() => {
    const Orig = window.WebSocket;
    window.__tiles_sockets = [];
    function Wrapped(url, protocols) {
        const ws = protocols === undefined ? new Orig(url) : new Orig(url, protocols);
        window.__tiles_sockets.push(ws);
        window.__tiles_ws = ws;
        return ws;
    }
    Wrapped.prototype = Orig.prototype;
    Wrapped.CONNECTING = 0; Wrapped.OPEN = 1; Wrapped.CLOSING = 2; Wrapped.CLOSED = 3;
    window.WebSocket = Wrapped;
})();
"""

# Send a takeTurn frame and await the server's takeTurnResponse.
_SEND_AND_WAIT_JS = """
async ([payload, timeoutMs]) => {
    const ws = window.__tiles_ws;
    if (!ws) return {ok: false, msg: 'no_socket'};
    if (ws.readyState !== 1) return {ok: false, msg: 'socket not open (' + ws.readyState + ')'};
    const room = window.__tiles_room || '';
    const player = window.__tiles_player || '';
    if (!room || !player) return {ok: false, msg: 'no room/player bound'};
    payload.room = room;
    payload.player = player;
    payload.gameName = 'azul';
    return await new Promise((resolve) => {
        let done = false;
        const handler = (ev) => {
            let data = null;
            try { data = JSON.parse(ev.data); } catch (e) { return; }
            if (!data || data.type !== 'takeTurnResponse') return;
            const p = data.payload || {};
            // Other turns are in flight on this socket too (the site's own
            // client auto-deals at round boundaries); only accept the
            // response to OUR turn type / player.
            if (p.turnType && p.turnType !== payload.turnType) return;
            if (p.player && p.player !== player) return;
            done = true;
            ws.removeEventListener('message', handler);
            resolve({ok: !!p.success, msg: p.message || ''});
        };
        ws.addEventListener('message', handler);
        ws.send(JSON.stringify({type: 'takeTurn', payload: payload}));
        setTimeout(() => {
            if (!done) {
                ws.removeEventListener('message', handler);
                resolve({ok: false, msg: 'ack timeout (' + timeoutMs + 'ms)'});
            }
        }, timeoutMs);
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

_LOBBY_COUNT_JS = """
() => {
    const players = document.querySelectorAll(
        '.lobby-ribbon-row .player-name, #sharing-link-row .badge');
    const avatars = document.querySelectorAll('.buddy-avatar');
    return Math.max(players.length, avatars.length);
}
"""


class BrowserSeat:
    """Async Playwright wrapper for one bot's seat in a live room."""

    ack_timeout_ms = 5000

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
        #: seat order as announced by startGameResponse
        self.site_players: List[str] = []
        #: everyone the lobby has announced so far (room responses)
        self.lobby_players: List[str] = []
        #: incremented on every authoritative state; lets callers wait
        #: for "a state newer than the one I saw" without racing the ack
        self.state_seq = 0
        #: dealTiles responses seen == rounds dealt so far
        self.rounds_dealt = 0
        self.in_lobby = False
        self.game_started = False
        self.game_over = False
        self.last_error: Optional[str] = None
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
        await self._page.add_init_script(_WS_CAPTURE_SCRIPT)

        url = protocol.seat_url(self.platform_url, self.player_name)
        logger.info("[%s] navigating to %s", self.player_name, url)
        # domcontentloaded: the site's socket keeps the network busy, so
        # 'networkidle' is unreliable.
        await self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await self._page.wait_for_selector(protocol.SEL_ROOM_INPUT, timeout=15000)
        await self._page.wait_for_timeout(500)

    async def join_room(self, timeout_s: float = 15) -> None:
        """Fill the room name and click Play (creates the room for the
        first joiner, joins otherwise — the site decides), then wait for
        the server's room response."""
        page = self._require_page()
        self.in_lobby = False
        self.last_error = None
        name_input = await page.query_selector(protocol.SEL_NAME_INPUT)
        if name_input is not None:
            await name_input.fill(self.player_name)
        room_input = await page.wait_for_selector(
            protocol.SEL_ROOM_INPUT, timeout=10000
        )
        await room_input.fill(self.room_name)
        await page.wait_for_timeout(200)
        # Bind room/player for the send helper before anything is emitted.
        await page.evaluate(
            """([room, player]) => {
                window.__tiles_room = room;
                window.__tiles_player = player;
            }""",
            [self.room_name, self.player_name],
        )
        play = await page.wait_for_selector(protocol.SEL_PLAY_BUTTON, timeout=10000)
        await play.click()

        deadline = asyncio.get_event_loop().time() + timeout_s
        while not self.in_lobby and asyncio.get_event_loop().time() < deadline:
            if self.last_error:
                raise RuntimeError(
                    f"{self.player_name} could not join room {self.room_name!r}: "
                    f"{self.last_error}"
                )
            await asyncio.sleep(0.2)
        if not self.in_lobby:
            raise RuntimeError(
                f"{self.player_name}: no room response from the platform "
                f"within {timeout_s:.0f}s"
            )
        await page.wait_for_timeout(500)

    async def start_game(self, timeout_s: float = 30) -> bool:
        """Host only: click Start Game once the button is shown and
        enabled (all players present)."""
        if not self.is_host:
            return False
        page = self._require_page()
        deadline = asyncio.get_event_loop().time() + timeout_s
        while asyncio.get_event_loop().time() < deadline:
            btn = await page.query_selector(protocol.SEL_START_LOBBY)
            if btn is not None:
                visible = await btn.evaluate(
                    "b => b.offsetHeight > 0 && !b.classList.contains('d-none') && !b.disabled"
                )
                if visible:
                    await btn.click()
                    logger.info("[%s] clicked Start Game", self.player_name)
                    await page.wait_for_timeout(1500)
                    return True
            await page.wait_for_timeout(500)
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

    async def wait_for_state(
        self, timeout_s: float = 10, since: Optional[int] = None
    ) -> bool:
        """Wait for an authoritative state newer than ``since`` (a
        ``state_seq`` value captured earlier). Returns immediately when
        one already arrived — e.g. inside the emit ack — so callers never
        wait out the timeout on a state they already have."""
        if since is not None and self.state_seq > since:
            return True
        self._state_event.clear()
        try:
            await asyncio.wait_for(self._state_event.wait(), timeout=timeout_s)
            return True
        except asyncio.TimeoutError:
            return False

    def is_my_turn(self) -> bool:
        from .state_translator import current_player_name

        return bool(
            self.site_game and current_player_name(self.site_game) == self.player_name
        )

    async def needs_deal(self) -> bool:
        """Empty table — the current player must emit dealTiles to start
        the next round (the site's client usually does it by itself)."""
        if self.site_game is not None:
            factories = self.site_game.get("factories") or []
            center = self.site_game.get("centerTiles")
            if center is None:
                center = self.site_game.get("center") or []
            real_center = [t for t in center if not protocol.is_first_player_tile(t)]
            if not any(factories) and not real_center:
                return True
            return False
        page = self._require_page()
        return bool(await page.evaluate(_NEEDS_DEAL_JS))

    async def check_game_over(self) -> bool:
        if self.game_over:
            return True
        page = self._require_page()
        if await page.evaluate(_GAME_OVER_JS):
            self.game_over = True
        return self.game_over

    async def lobby_player_count(self) -> int:
        if self.lobby_players:
            return len(self.lobby_players)
        page = self._require_page()
        return int(await page.evaluate(_LOBBY_COUNT_JS) or 0)

    async def dom_snapshot(self) -> Optional[Dict[str, Any]]:
        """Scrape the board from the DOM, shaped like the site's game
        object (``currentPlayer`` is only known when it is our turn)."""
        page = self._require_page()
        try:
            raw = await page.evaluate(DOM_SNAPSHOT_JS)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[%s] DOM snapshot failed: %s", self.player_name, exc)
            return None
        return snapshot_to_site_game(
            raw or {}, self.player_name, self.site_players, max(1, self.rounds_dealt)
        )

    # -- actions --------------------------------------------------------------

    async def _send(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        page = self._require_page()
        return await page.evaluate(
            _SEND_AND_WAIT_JS, [dict(payload), self.ack_timeout_ms]
        )

    async def emit_action(
        self, choose: Dict[str, Any], place: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Two-step move with server acks. On a rejected placement,
        fall back to the floor so the seat never wedges the room (the
        local validator makes rejections rare; this guards against
        state drift). Returns {'ok': bool, 'msg': str, 'fallback': bool}.
        """
        page = self._require_page()
        result = await self._send(choose)
        if not result.get("ok"):
            return {"ok": False, "msg": f"chooseTiles: {result.get('msg')}",
                    "fallback": False}
        await page.wait_for_timeout(150)

        result = await self._send(place)
        if result.get("ok"):
            await page.wait_for_timeout(200)
            return {"ok": True, "msg": "", "fallback": False}

        logger.warning(
            "[%s] placeTiles rejected (%s); floor fallback",
            self.player_name,
            result.get("msg"),
        )
        result = await self._send(protocol.place_tiles_payload(None))
        await page.wait_for_timeout(200)
        return {
            "ok": bool(result.get("ok")),
            "msg": result.get("msg", ""),
            "fallback": True,
        }

    async def deal_tiles(self) -> bool:
        result = await self._send(protocol.deal_tiles_payload())
        page = self._require_page()
        await page.wait_for_timeout(500)
        return bool(result.get("ok"))

    # -- internals -------------------------------------------------------------

    def _require_page(self):
        if self._page is None:
            raise RuntimeError(
                f"seat {self.player_name} not launched; call launch() first"
            )
        return self._page

    def _handle_websocket(self, ws) -> None:
        logger.info("[%s] websocket %s", self.player_name, ws.url)
        ws.on("framereceived", lambda payload: self._on_frame(payload))

    def _remember_lobby(self, data: Dict[str, Any]) -> None:
        names = data.get("players")
        if isinstance(names, list):
            for item in names:
                name = item.get("name") if isinstance(item, dict) else item
                if isinstance(name, str) and name and name not in self.lobby_players:
                    self.lobby_players.append(name)

    def _on_frame(self, payload: str) -> None:
        parsed = parse_frame(payload)
        if not parsed:
            return
        event, data = parsed
        if not isinstance(data, dict):
            return
        if event == EV_TAKE_TURN_RESPONSE:
            if data.get("success") and isinstance(data.get("game"), dict):
                self.site_game = data["game"]
                self.game_started = True
                self.state_seq += 1
                if data.get("turnType") == protocol.TURN_DEAL:
                    self.rounds_dealt += 1
                if data["game"].get("gameOver"):
                    self.game_over = True
                self._state_event.set()
            elif not data.get("success") and data.get("message"):
                logger.debug("[%s] takeTurn rejected: %s", self.player_name, data["message"])
        elif event == EV_START_GAME_RESPONSE:
            if data.get("success"):
                self.game_started = True
                players = data.get("players") or []
                self.site_players = [
                    p.get("name", "") for p in players if isinstance(p, dict)
                ]
                self._state_event.set()
        elif event in (EV_JOIN_ROOM_RESPONSE, EV_CREATE_ROOM_RESPONSE):
            if data.get("success"):
                self.in_lobby = True
                self.last_error = None
                if event == EV_CREATE_ROOM_RESPONSE and self.player_name not in self.lobby_players:
                    self.lobby_players.append(self.player_name)
                if event == EV_JOIN_ROOM_RESPONSE and not self.lobby_players and self.player_name:
                    # First successful join: the list includes us.
                    pass
                self._remember_lobby(data)
            elif not self.in_lobby:
                # "Can't find that room" is normal for the host: the site
                # follows up with createRoom. Any other refusal (room in
                # use, name taken, full) surfaces through join_room().
                message = str(data.get("message", "")) or f"{event} failed"
                if "find that room" not in message.lower():
                    self.last_error = message
        elif event == EV_END_GAME_RESPONSE:
            self.game_over = True
            self._state_event.set()
