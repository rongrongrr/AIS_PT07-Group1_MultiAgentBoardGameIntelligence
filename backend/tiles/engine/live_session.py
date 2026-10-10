"""LiveSession: the full Decision Stack playing on buddyboardgames.com.

Orchestrates N ``BrowserSeat``s in one room. Every turn follows the same
node order as local play (sense → profile → decide → validate → execute
→ observe → explain), with two live-specific twists:

* **The site is the dealer, the local engine is the referee.** Each
  turn re-translates the freshest authoritative site state instead of
  simulating forward — this makes round transitions trivial (the fix
  for the Milestone-1 fragility) — while every proposed move is still
  gated by the local Validator before it is emitted.
* **Opponent moves are inferred**, not received: consecutive
  authoritative states are diffed (``infer_action``) so the Profiler
  can observe human/remote players too.

Events emitted through ``on_event`` use the same shapes as docs/API.md
so the server can broadcast live and local sessions identically.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from tiles.agents.base import (
    DecisionContext,
    Explainer,
    Profiler,
    Tactician,
)
from tiles.agents.validator import Validator
from tiles.core import GameState, apply_action

from .browser_seat import BrowserSeat
from .protocol import DEFAULT_PLATFORM_URL
from .state_translator import (
    action_to_site_moves,
    infer_action,
    site_state_to_game_state,
)

logger = logging.getLogger(__name__)

EventCallback = Callable[[Dict[str, Any]], Union[None, Awaitable[None]]]

_LOBBY_COUNT_JS = """
() => {
    const players = document.querySelectorAll(
        '.lobby-ribbon-row .player-name, #sharing-link-row .badge');
    const avatars = document.querySelectorAll('.buddy-avatar');
    return Math.max(players.length, avatars.length);
}
"""


@dataclass
class LiveSeat:
    """One configured seat. ``tactician=None`` marks a human seat (no
    browser is launched; the human joins via the room link)."""

    name: str
    tactician: Optional[Tactician] = None

    @property
    def is_bot(self) -> bool:
        return self.tactician is not None


@dataclass
class LiveSessionConfig:
    room_name: str
    seats: List[LiveSeat]
    platform_url: str = DEFAULT_PLATFORM_URL
    headless: bool = True
    move_delay_ms: int = 0
    turn_timeout_s: float = 120.0  # waiting on humans can be slow
    human_join_timeout_s: float = 300.0
    max_steps: int = 500


class LiveSession:
    """Runs one live game end to end."""

    def __init__(
        self,
        config: LiveSessionConfig,
        on_event: Optional[EventCallback] = None,
        profiler: Optional[Profiler] = None,
        explainer: Optional[Explainer] = None,
    ) -> None:
        self.config = config
        self.on_event = on_event
        self.profiler = profiler
        self.explainer = explainer
        self.validator = Validator()
        self.seats: Dict[str, BrowserSeat] = {}
        self._stop = asyncio.Event()
        self._step = 0
        self._last_state: Optional[GameState] = None

    # -- public ---------------------------------------------------------------

    @property
    def room_url(self) -> str:
        return f"{self.config.platform_url}?room={self.config.room_name}"

    async def stop(self) -> None:
        self._stop.set()

    async def run(self) -> Dict[str, Any]:
        """Join, play, and return a summary. Always closes browsers."""
        bots = [s for s in self.config.seats if s.is_bot]
        humans = [s for s in self.config.seats if not s.is_bot]
        if not bots:
            raise ValueError("a live session needs at least one bot seat")

        try:
            await self._join_all(bots, humans)
            await self._emit(
                {"type": "status", "status": "running", "room_url": self.room_url}
            )
            summary = await self._game_loop(bots)
            return summary
        except Exception as exc:
            await self._emit(
                {"type": "log", "level": "error", "message": str(exc)}
            )
            raise
        finally:
            await asyncio.gather(
                *(seat.close() for seat in self.seats.values()),
                return_exceptions=True,
            )

    # -- setup ----------------------------------------------------------------

    async def _join_all(self, bots: List[LiveSeat], humans: List[LiveSeat]) -> None:
        for i, seat_cfg in enumerate(bots):
            self.seats[seat_cfg.name] = BrowserSeat(
                room_name=self.config.room_name,
                player_name=seat_cfg.name,
                platform_url=self.config.platform_url,
                headless=self.config.headless,
                is_host=(i == 0),
            )
        await self._emit({"type": "status", "status": "connecting"})
        await asyncio.gather(*(s.launch() for s in self.seats.values()))

        host = self._host()
        await host.join_room()
        await asyncio.sleep(1)
        for seat in self.seats.values():
            if seat is not host:
                await seat.join_room()
                await asyncio.sleep(0.5)

        await self._emit(
            {
                "type": "status",
                "status": "lobby",
                "room_url": self.room_url,
                "waiting_for_humans": [h.name for h in humans],
            }
        )
        if humans:
            await self._wait_for_humans(len(self.config.seats))
        if not await host.start_game():
            raise RuntimeError("host could not start the game")
        # Give every seat a moment to receive the opening state.
        await asyncio.sleep(2)

    async def _wait_for_humans(self, expected_total: int) -> None:
        host = self._host()
        deadline = time.monotonic() + self.config.human_join_timeout_s
        while time.monotonic() < deadline and not self._stop.is_set():
            count = await host._require_page().evaluate(_LOBBY_COUNT_JS) or 0
            if count >= expected_total:
                await self._emit(
                    {"type": "log", "level": "info",
                     "message": f"all {expected_total} players in lobby"}
                )
                return
            await asyncio.sleep(2)
        logger.warning("timed out waiting for humans; starting anyway")

    # -- game loop -------------------------------------------------------------

    async def _game_loop(self, bots: List[LiveSeat]) -> Dict[str, Any]:
        tacticians = {s.name: s.tactician for s in bots}
        idle_polls = 0

        while not self._stop.is_set() and self._step < self.config.max_steps:
            seat = self._freshest_seat()
            if seat is None or seat.site_game is None:
                await asyncio.sleep(1)
                continue

            state = site_state_to_game_state(seat.site_game)
            self._observe_transition(state)

            if state.is_game_over or await seat.check_game_over():
                return await self._finish(state)

            current_name = seat.site_game.get("currentPlayer", "")
            actor = self.seats.get(current_name)
            if actor is None or current_name not in tacticians:
                # A human's turn: wait for the next authoritative state.
                got = await self._any_state_update(self.config.turn_timeout_s)
                if not got:
                    idle_polls += 1
                    if idle_polls > 3:
                        await self._emit(
                            {"type": "log", "level": "warning",
                             "message": f"no state change while waiting on "
                                        f"{current_name!r} for "
                                        f"{4 * self.config.turn_timeout_s:.0f}s"}
                        )
                        idle_polls = 0
                continue

            idle_polls = 0
            # Fresh round with empty table? The current player must deal.
            local_state = site_state_to_game_state(actor.site_game or seat.site_game)
            if not self.validator.legal_actions(local_state):
                if await actor.needs_deal():
                    await self._emit(
                        {"type": "log", "level": "info",
                         "message": f"{current_name} dealing round "
                                    f"{local_state.round_number}"}
                    )
                    await actor.deal_tiles()
                    await actor.wait_for_state(10)
                    continue
                if await actor.check_game_over():
                    return await self._finish(local_state)
                await asyncio.sleep(1)
                continue

            await self._play_bot_turn(actor, tacticians[current_name], local_state)
            if self.config.move_delay_ms:
                await asyncio.sleep(self.config.move_delay_ms / 1000)

        state = (
            site_state_to_game_state(self._freshest_seat().site_game)
            if self._freshest_seat() and self._freshest_seat().site_game
            else None
        )
        status = "aborted" if self._stop.is_set() else "stalled"
        await self._emit({"type": "status", "status": status})
        return {"status": status, "steps": self._step,
                "scores": state.scores() if state else []}

    async def _play_bot_turn(
        self, seat: BrowserSeat, tactician: Tactician, state: GameState
    ) -> None:
        self._step += 1
        step = self._step
        timing: Dict[str, float] = {}
        t_total = time.perf_counter()

        # profile
        profiles = None
        opponent_policy = None
        if self.profiler is not None:
            profiles = self.profiler.profiles(state.num_players)
            opponent_policy = self.profiler.predict

        # decide
        legal = self.validator.legal_actions(state)
        ctx = DecisionContext(
            state=state,
            player_index=state.current_player,
            legal=legal,
            profiles=profiles,
            opponent_policy=opponent_policy,
        )
        t0 = time.perf_counter()
        decision = tactician.decide(ctx)
        timing["decide_ms"] = (time.perf_counter() - t0) * 1000

        # validate (with fallback to the first legal action)
        t0 = time.perf_counter()
        attempts = 1
        result = self.validator.validate(state, decision.action)
        if not result.ok:
            logger.warning(
                "[%s] tactician proposed illegal %s (%s); using fallback",
                seat.player_name, decision.action, result.violation.message,
            )
            decision.action = legal[0]
            attempts = 2
            result = self.validator.validate(state, decision.action)
        timing["validate_ms"] = (time.perf_counter() - t0) * 1000

        # execute on the live site
        state_before = state.clone()
        choose, place = action_to_site_moves(decision.action)
        t0 = time.perf_counter()
        outcome = await seat.emit_action(choose, place)
        await seat.wait_for_state(15)
        timing["execute_ms"] = (time.perf_counter() - t0) * 1000
        if not outcome.get("ok"):
            await self._emit(
                {"type": "log", "level": "error",
                 "message": f"move rejected by site: {outcome.get('msg')}"}
            )
            return

        # observe (our own move, on the mirrored state)
        move = None
        try:
            local = state_before.clone()
            move = apply_action(local, decision.action)
            if self.profiler is not None:
                self.profiler.observe(
                    state_before, decision.action, move,
                    decision_ms=timing["decide_ms"],
                )
        except ValueError:
            pass  # mirrored-state drift; the site accepted it, move on

        # explain
        explanation = None
        if self.explainer is not None:
            t0 = time.perf_counter()
            explanation = self.explainer.explain(ctx, decision, move)
            timing["explain_ms"] = (time.perf_counter() - t0) * 1000

        state_after = (
            site_state_to_game_state(seat.site_game) if seat.site_game else None
        )
        timing["total_ms"] = (time.perf_counter() - t_total) * 1000
        record = {
            "step": step,
            "round": state_before.round_number,
            "player_index": state_before.current_player,
            "player_name": seat.player_name,
            "tactician": tactician.name,
            "action": decision.action.to_dict(),
            "state_before": state_before.to_dict(),
            "state_after": state_after.to_dict() if state_after else None,
            "explanation": explanation.to_dict() if explanation else None,
            "report": decision.report.to_dict() if decision.report else None,
            "profiles": (
                {str(i): p.to_dict() for i, p in profiles.items()}
                if profiles
                else None
            ),
            "validation": {"ok": True, "violation": None, "attempts": attempts,
                           "site_fallback": outcome.get("fallback", False)},
            "timing": {k: round(v, 2) for k, v in timing.items()},
        }
        await self._emit({"type": "move", "step": step, "record": record})
        if state_after is not None:
            await self._emit(
                {"type": "state", "step": step, "state": state_after.to_dict()}
            )

    # -- observation of opponents ------------------------------------------------

    def _observe_transition(self, state: GameState) -> None:
        """Diff against the previous mirrored state so the Profiler sees
        opponent (human/remote) moves too."""
        prev = self._last_state
        self._last_state = state
        if prev is None or self.profiler is None:
            return
        mover = prev.current_player
        # Only infer plain drafting moves by players we did not act for
        # in _play_bot_turn (bots already observed themselves).
        mover_name = prev.players[mover].name if mover < len(prev.players) else ""
        if mover_name in self.seats:
            return
        if prev.round_number != state.round_number:
            return
        action = infer_action(prev, state, mover)
        if action is None:
            return
        try:
            local = prev.clone()
            move = apply_action(local, action)
            self.profiler.observe(prev, action, move)
        except ValueError:
            pass

    # -- finish -----------------------------------------------------------------

    async def _finish(self, state: GameState) -> Dict[str, Any]:
        scores = state.scores()
        winner = max(range(len(scores)), key=lambda i: scores[i]) if scores else None
        await self._emit(
            {
                "type": "game_over",
                "winner": winner,
                "scores": scores,
                "players": [p.name for p in state.players],
            }
        )
        return {
            "status": "completed",
            "steps": self._step,
            "scores": scores,
            "winner": winner,
            "players": [p.name for p in state.players],
        }

    # -- utilities ---------------------------------------------------------------

    def _host(self) -> BrowserSeat:
        for seat in self.seats.values():
            if seat.is_host:
                return seat
        return next(iter(self.seats.values()))

    def _freshest_seat(self) -> Optional[BrowserSeat]:
        """Any seat with an authoritative state (host preferred)."""
        host = self._host() if self.seats else None
        if host is not None and host.site_game is not None:
            return host
        for seat in self.seats.values():
            if seat.site_game is not None:
                return seat
        return host

    async def _any_state_update(self, timeout_s: float) -> bool:
        waiters = [
            asyncio.create_task(seat.wait_for_state(timeout_s))
            for seat in self.seats.values()
        ]
        done, pending = await asyncio.wait(
            waiters, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        return any(task.result() for task in done if not task.cancelled())

    async def _emit(self, event: Dict[str, Any]) -> None:
        if self.on_event is None:
            return
        try:
            result = self.on_event(event)
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 — observers must not kill the game
            logger.exception("on_event callback failed")
