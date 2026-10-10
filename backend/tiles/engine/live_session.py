"""LiveSession: the full Decision Stack playing on buddyboardgames.com.

Orchestrates N seats (one Chromium browser per bot) in one room. Every
bot turn runs the *same* Decision Stack half-turns as local play
(``TurnPipeline.propose`` → execute on the site → ``TurnPipeline.conclude``),
with the live-specific twists:

* **The site is the dealer, the local engine is the referee.** Each
  turn re-translates the freshest authoritative site state instead of
  simulating forward — this makes round transitions trivial (the fix
  for the Milestone-1 fragility) — while every proposed move is still
  gated by the local Validator before it is emitted.
* **Opponent moves are inferred**, not received: consecutive
  authoritative states are diffed (``infer_action``) so the Profiler
  can observe human/remote players too.
* **Everything is recorded** in the same ledger, with the same
  TurnRecord shape, so replay, profiling and experiments treat live
  games exactly like local ones.

Events emitted through ``on_event`` use the shapes in docs/API.md so the
server can broadcast live and local sessions identically.

The seat transport is injectable (``seat_factory``) so the whole loop —
joining, the opening deal, turns, round transitions, game over — is
exercised offline by ``tests/test_live_session.py`` with a fake seat.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union

from tiles.agents.base import Explainer, Profiler, Tactician
from tiles.agents.validator import Validator
from tiles.core import GameState, apply_action, winner_index
from tiles.orchestration import TurnPipeline

from .protocol import DEFAULT_PLATFORM_URL, room_link
from .state_translator import (
    action_to_site_moves,
    infer_action,
    site_state_to_game_state,
)

logger = logging.getLogger(__name__)

EventCallback = Callable[[Dict[str, Any]], Union[None, Awaitable[None]]]
#: (room_name, player_name, platform_url, headless, is_host) -> seat
SeatFactory = Callable[..., Any]

_MAX_CONSECUTIVE_REJECTS = 3


def _browser_seat_factory(**kwargs):
    from .browser_seat import BrowserSeat  # lazy: Playwright optional

    return BrowserSeat(**kwargs)


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
    deal_timeout_s: float = 8.0  # opening deal grace before we deal ourselves
    # Round boundary: a human's browser deals by itself after the site's
    # wall-tiling animation; bot pages were never seen to. Wait this long
    # for a deal to show up before dealing ourselves (a late duplicate
    # deal is rejected by the server and ignored by our ack matching).
    deal_grace_s: float = 4.0
    state_timeout_s: float = 15.0  # ack → state after our own move
    max_steps: int = 500
    poll_interval_s: float = 1.0


class LiveSession:
    """Runs one live game end to end."""

    def __init__(
        self,
        config: LiveSessionConfig,
        on_event: Optional[EventCallback] = None,
        profiler: Optional[Profiler] = None,
        explainer: Optional[Explainer] = None,
        ledger=None,
        session_id: Optional[str] = None,
        stop_event: Optional[threading.Event] = None,
        seat_factory: Optional[SeatFactory] = None,
    ) -> None:
        self.config = config
        self.on_event = on_event
        self.ledger = ledger
        self.session_id = session_id or f"live_{int(time.time())}"
        self.stop_event = stop_event
        self.seat_factory = seat_factory or _browser_seat_factory
        self.validator = Validator()
        self.pipeline = TurnPipeline(
            validator=self.validator,
            tacticians={},
            profiler=profiler,
            explainer=explainer,
        )
        self._tactician_by_name: Dict[str, Tactician] = {
            s.name: s.tactician for s in config.seats if s.tactician is not None
        }
        self.seats: Dict[str, Any] = {}
        self._stop = asyncio.Event()
        self._step = 0
        self._last_state: Optional[GameState] = None
        self._last_state_at: Optional[float] = None
        self._rounds_recorded: set = set()
        self._consecutive_rejects = 0

    # -- public ---------------------------------------------------------------

    @property
    def profiler(self) -> Optional[Profiler]:
        return self.pipeline.profiler

    @property
    def room_url(self) -> str:
        """Share link for humans (room pre-filled; they type a name)."""
        return room_link(self.config.platform_url, self.config.room_name)

    def _status(self, status: str, **extra) -> Dict[str, Any]:
        return {
            "type": "status",
            "status": status,
            "room_url": self.room_url,
            "room_name": self.config.room_name,
            **extra,
        }

    @staticmethod
    def _translate(seat) -> GameState:
        """Translate a seat's authoritative state, numbering rounds by
        the dealTiles responses the seat has seen."""
        rounds = getattr(seat, "rounds_dealt", 0) or 0
        return site_state_to_game_state(
            seat.site_game, round_number=rounds if rounds > 0 else None
        )

    async def stop(self) -> None:
        self._stop.set()

    def _should_stop(self) -> bool:
        # Checked inline too, so a stop lands even when the loop never
        # yields long enough for the watcher task to run.
        if self.stop_event is not None and self.stop_event.is_set():
            self._stop.set()
        return self._stop.is_set()

    async def run(self) -> Dict[str, Any]:
        """Join, play, and return a summary. Always closes browsers."""
        bots = [s for s in self.config.seats if s.is_bot]
        humans = [s for s in self.config.seats if not s.is_bot]
        if not bots:
            raise ValueError("a live session needs at least one bot seat")

        # A stop must land even mid-await (browser launch, lobby, a long
        # wait on a human's turn), so the game races the stop signal and
        # is cancelled wherever it is.
        game = asyncio.ensure_future(self._play(bots, humans))
        stopper = asyncio.ensure_future(self._wait_for_stop())
        try:
            await asyncio.wait({game, stopper}, return_when=asyncio.FIRST_COMPLETED)
            if game.done():
                return game.result()
            game.cancel()
            await asyncio.wait({game}, timeout=5)
            await self._log("info", "session stopped by request", phase="session")
            return await self._end("aborted")
        finally:
            stopper.cancel()
            if not game.done():
                game.cancel()
            await asyncio.gather(
                *(seat.close() for seat in self.seats.values()),
                return_exceptions=True,
            )

    async def _play(self, bots: List[LiveSeat], humans: List[LiveSeat]) -> Dict[str, Any]:
        try:
            await self._join_all(bots, humans)
            await self._ensure_initial_state()
            self._ledger_status("running")
            await self._emit(self._status("running"))
            return await self._game_loop()
        except Exception as exc:
            await self._log("error", str(exc), phase="session")
            raise

    # -- setup ----------------------------------------------------------------

    async def _join_all(self, bots: List[LiveSeat], humans: List[LiveSeat]) -> None:
        for i, seat_cfg in enumerate(bots):
            self.seats[seat_cfg.name] = self.seat_factory(
                room_name=self.config.room_name,
                player_name=seat_cfg.name,
                platform_url=self.config.platform_url,
                headless=self.config.headless,
                is_host=(i == 0),
            )
        self._ledger_status("connecting")
        await self._emit(self._status("connecting"))
        await self._log(
            "info",
            f"launching {len(self.seats)} Chromium seat(s) "
            f"({'headless' if self.config.headless else 'headed'}) for "
            f"{self.config.platform_url}",
            phase="connect",
        )
        await asyncio.gather(*(s.launch() for s in self.seats.values()))
        await self._log("info", "browsers ready; host creating the room", phase="connect")

        host = self._host()
        await self._create_room_with_retry(host)
        await asyncio.sleep(self.config.poll_interval_s)
        for seat in self.seats.values():
            if seat is not host:
                await seat.join_room()
                await self._log(
                    "info", f"{seat.player_name} joined the room", phase="lobby",
                    player=seat.player_name,
                )
                await asyncio.sleep(self.config.poll_interval_s / 2)

        self._ledger_status("lobby")
        await self._emit(
            self._status("lobby", waiting_for_humans=[h.name for h in humans])
        )
        await self._log(
            "info",
            f"{len(self.seats)} bot seat(s) in room {self.config.room_name!r}"
            + (f"; waiting for humans: {', '.join(h.name for h in humans)}" if humans else ""),
            phase="lobby",
        )
        if humans:
            await self._wait_for_humans(len(self.config.seats))
        await self._log("info", "host starting the game", phase="lobby", player=host.player_name)
        if not await host.start_game():
            raise RuntimeError("host could not start the game")
        await self._log("info", "game started; waiting for the opening deal", phase="lobby",
                        player=host.player_name)

    async def _create_room_with_retry(self, host, attempts: int = 3) -> None:
        """The site refuses a room name while an earlier game with that
        name is still alive (players disconnected but the room not yet
        expired). Rather than fail the demo, retry under a fresh name and
        announce it (status events carry ``room_name``/``room_url``)."""
        base = self.config.room_name
        for attempt in range(attempts):
            try:
                await host.join_room()
                await self._log(
                    "info", f"{host.player_name} created room {self.config.room_name!r}",
                    phase="lobby", player=host.player_name,
                )
                return
            except RuntimeError as exc:
                busy = "already in use" in str(exc).lower()
                if not busy or attempt == attempts - 1:
                    raise
                new_name = f"{base[:16]}-{random.randint(10, 99)}"
                await self._log(
                    "warning",
                    f"room {self.config.room_name!r} is still in use on the "
                    f"platform; retrying as {new_name!r}",
                    phase="lobby",
                )
                self.config.room_name = new_name
                for seat in self.seats.values():
                    seat.room_name = new_name
                await self._emit(self._status("connecting"))

    async def _wait_for_humans(self, expected_total: int) -> None:
        host = self._host()
        deadline = time.monotonic() + self.config.human_join_timeout_s
        while time.monotonic() < deadline and not self._should_stop():
            count = await host.lobby_player_count()
            if count >= expected_total:
                await self._log(
                    "info", f"all {expected_total} players in lobby", phase="lobby"
                )
                return
            await asyncio.sleep(2 * self.config.poll_interval_s)
        await self._log(
            "warning", "timed out waiting for humans; starting anyway", phase="lobby"
        )

    async def _ensure_initial_state(self) -> None:
        """Make sure *some* seat holds an authoritative state before the
        loop starts. The site normally auto-deals through the first
        player's client; if nothing arrives the host deals, and as a last
        resort the board is read off the DOM."""
        if await self._wait_any_state(self.config.deal_timeout_s):
            await self._log("info", "opening state received from the platform", phase="deal")
            return
        host = self._host()
        await self._log(
            "info",
            "no opening state from the platform; host emits dealTiles",
            phase="deal",
            player=host.player_name,
        )
        await host.deal_tiles()
        if await self._wait_any_state(self.config.deal_timeout_s):
            return
        snapshot = await host.dom_snapshot()
        if snapshot and snapshot.get("players"):
            host.site_game = snapshot
            await self._log(
                "warning", "using DOM snapshot as the opening state", phase="deal",
                player=host.player_name,
            )
            return
        raise RuntimeError("no game state received from the platform after start")

    async def _wait_any_state(self, timeout_s: float) -> bool:
        if any(seat.site_game for seat in self.seats.values()):
            return True
        await self._any_state_update(timeout_s)
        return any(seat.site_game for seat in self.seats.values())

    # -- game loop -------------------------------------------------------------

    async def _game_loop(self) -> Dict[str, Any]:
        idle_polls = 0
        poll = self.config.poll_interval_s

        while not self._should_stop() and self._step < self.config.max_steps:
            seat = self._freshest_seat()
            if seat is None or seat.site_game is None:
                await asyncio.sleep(poll)
                continue

            state = self._translate(seat)
            self._observe_transition(state)

            if state.is_game_over or await seat.check_game_over():
                return await self._finish(state)

            current_name = state.players[state.current_player].name
            actor = self.seats.get(current_name)
            if actor is None:
                # A human's (or unknown) turn: wait for the next state.
                got = await self._any_state_update(self.config.turn_timeout_s)
                if not got:
                    idle_polls += 1
                    if idle_polls > 3:
                        await self._log(
                            "warning",
                            f"no state change while waiting on {current_name!r} "
                            f"for {4 * self.config.turn_timeout_s:.0f}s",
                            phase="wait",
                        )
                        idle_polls = 0
                continue

            idle_polls = 0
            # Decide from the freshest state in the room (another seat's
            # page may have received the latest frame before the actor's).
            local_state = state
            if not self.validator.legal_actions(local_state):
                # Empty table at a round boundary. The site's own client
                # normally deals; give it a moment, then deal ourselves.
                if await actor.needs_deal():
                    seq = actor.state_seq
                    if await actor.wait_for_state(self.config.deal_grace_s, since=seq):
                        continue
                    await self._log(
                        "info",
                        f"dealing round {local_state.round_number + 1}",
                        phase="deal",
                        player=current_name,
                    )
                    await actor.deal_tiles()
                    await actor.wait_for_state(self.config.state_timeout_s, since=seq)
                    continue
                if await actor.check_game_over():
                    return await self._finish(local_state)
                await asyncio.sleep(poll)
                continue

            await self._play_bot_turn(actor, local_state)
            if self.config.move_delay_ms:
                await asyncio.sleep(self.config.move_delay_ms / 1000)

        return await self._end("aborted" if self._stop.is_set() else "stalled")

    async def _end(self, status: str) -> Dict[str, Any]:
        seat = self._freshest_seat()
        state = self._translate(seat) if seat is not None and seat.site_game else None
        self._ledger_status(status)
        await self._emit(self._status(status))
        return {
            "status": status,
            "steps": self._step,
            "scores": state.scores() if state else [],
            "players": [p.name for p in state.players] if state else [],
        }

    def _sync_tacticians(self, state: GameState) -> None:
        """Seat order on the site is only known from its state; map it
        onto the pipeline's index-keyed tacticians every turn."""
        for i, board in enumerate(state.players):
            tactician = self._tactician_by_name.get(board.name)
            if tactician is not None:
                self.pipeline.tacticians[i] = tactician
        if self.profiler is not None:
            self.profiler.register_players([p.name for p in state.players])

    async def _play_bot_turn(self, seat, state: GameState) -> None:
        turn_start = time.perf_counter()
        self._sync_tacticians(state)
        proposal = self.pipeline.propose(state)

        choose, place = action_to_site_moves(proposal.action)
        seq = seat.state_seq
        t0 = time.perf_counter()
        outcome = await seat.emit_action(choose, place)
        got_state = await seat.wait_for_state(self.config.state_timeout_s, since=seq)
        execute_ms = (time.perf_counter() - t0) * 1000

        if not outcome.get("ok"):
            self._consecutive_rejects += 1
            await self._log(
                "error",
                f"move rejected by the platform: {outcome.get('msg')} "
                f"({proposal.action})",
                phase="execute",
                player=seat.player_name,
            )
            if self._consecutive_rejects >= _MAX_CONSECUTIVE_REJECTS:
                raise RuntimeError(
                    "the platform rejected "
                    f"{self._consecutive_rejects} consecutive moves"
                )
            # Re-sync on the next authoritative state and try again.
            await seat.wait_for_state(self.config.state_timeout_s, since=seq)
            return
        self._consecutive_rejects = 0
        if not got_state:
            await self._log(
                "warning",
                "no state update after the move; continuing on the ack",
                phase="execute",
                player=seat.player_name,
            )

        # Mirror the move locally so the Profiler/Explainer see a MoveResult.
        move = None
        try:
            move = apply_action(state.clone(), proposal.action)
        except ValueError:
            pass  # mirrored-state drift; the site accepted it, move on

        self._step += 1
        state_after = self._translate(seat) if seat.site_game else None
        record = self.pipeline.conclude(
            proposal,
            move,
            state_after,
            self._step,
            extra_timing={"execute_ms": execute_ms},
            extra_validation={"site_fallback": bool(outcome.get("fallback"))},
            turn_start=turn_start,
        )
        if self.ledger is not None:
            self.ledger.record_move(self.session_id, record)
        await self._emit({"type": "move", "step": self._step, "record": record})
        if state_after is not None and state_after.round_number == state.round_number:
            # Baseline for the next seat's move, so a quick human reply
            # isn't diffed against the state before our own move.
            self._last_state = state_after
            self._last_state_at = time.perf_counter()
        if state_after is not None:
            await self._emit(
                {"type": "state", "step": self._step, "state": state_after.to_dict()}
            )

    # -- observation of opponents ------------------------------------------------

    def _observe_transition(self, state: GameState) -> None:
        """Diff against the previous mirrored state so moves by seats we
        don't control (humans, remote players) are recorded and profiled
        like our own, and round boundaries are reported."""
        prev = self._last_state
        prev_at = self._last_state_at
        if prev is not None and prev.to_dict() == state.to_dict():
            return  # re-read of the same frame; keep the think-time clock
        self._last_state = state
        self._last_state_at = time.perf_counter()
        if prev is None:
            return
        mover = prev.current_player
        # Bots record themselves in conclude(); only infer other seats.
        mover_name = prev.players[mover].name if mover < len(prev.players) else ""
        if mover_name and mover_name not in self.seats:
            action = infer_action(prev, state, mover)
            if action is not None:
                self._record_observed_move(prev, state, mover, action, prev_at)
        if prev.round_number != state.round_number:
            self._record_round(prev.round_number, state)

    def _record_observed_move(
        self,
        prev: GameState,
        state: GameState,
        mover: int,
        action,
        prev_at: Optional[float],
    ) -> None:
        before = prev.clone()
        before.current_player = mover
        try:
            move = apply_action(before.clone(), action)
        except ValueError:
            return
        # Think time: from the state that put them on turn to their move.
        think_ms = (time.perf_counter() - prev_at) * 1000 if prev_at else None
        if self.profiler is not None:
            self.profiler.observe(before, action, move, think_ms)

        self._step += 1
        timing = {"decide_ms": round(think_ms, 3)} if think_ms is not None else {}
        if think_ms is not None:
            timing["total_ms"] = timing["decide_ms"]
        record = {
            "step": self._step,
            "round": before.round_number,
            "player_index": mover,
            "player_name": before.players[mover].name,
            "tactician": "human",
            "action": action.to_dict(),
            "state_before": before.to_dict(),
            "state_after": state.to_dict(),
            "explanation": None,
            "report": None,
            "profiles": {},
            "validation": {"ok": True, "violation": None, "attempts": 1, "inferred": True},
            "timing": timing,
        }
        if self.ledger is not None:
            self.ledger.record_move(self.session_id, record)
        self._emit_nowait({"type": "move", "step": self._step, "record": record})

    def _record_round(self, round_number: int, state_after: GameState) -> None:
        if round_number in self._rounds_recorded:
            return
        self._rounds_recorded.add(round_number)
        result = {
            "round": round_number,
            "tilings": [],  # the site resolves wall-tiling server-side
            "floor_penalties": [],
            "scores": state_after.scores(),
            "game_over": state_after.is_game_over,
            "bonuses": None,
        }
        if self.ledger is not None:
            try:
                self.ledger.record_round(self.session_id, round_number, result)
            except Exception:  # noqa: BLE001 — duplicate round on resync
                pass
        self._emit_nowait({"type": "round", "round": round_number, "result": result})

    # -- finish -----------------------------------------------------------------

    async def _finish(self, state: GameState) -> Dict[str, Any]:
        scores = state.scores()
        winner = winner_index(state.players)  # None = shared win
        players = [p.name for p in state.players]
        result = {
            "status": "completed",
            "steps": self._step,
            "scores": scores,
            "winner": winner,
            "winner_name": players[winner] if winner is not None else "",
            "players": players,
            "rounds": state.round_number,
        }
        profiles: List[dict] = []
        if self.profiler is not None:
            profiles = [
                self.profiler.profile(i).to_dict() for i in range(state.num_players)
            ]
        if self.ledger is not None:
            if profiles:
                self.ledger.save_profiles(self.session_id, profiles)
            self.ledger.finish_session(self.session_id, result)
        await self._emit(
            {
                "type": "game_over",
                "winner": winner,
                "scores": scores,
                "players": players,
                "bonuses": None,
            }
        )
        return result

    # -- utilities ---------------------------------------------------------------

    def _host(self):
        for seat in self.seats.values():
            if seat.is_host:
                return seat
        return next(iter(self.seats.values()))

    def _freshest_seat(self):
        """The seat holding the newest authoritative state."""
        best = None
        for seat in self.seats.values():
            if seat.site_game is None:
                continue
            if best is None or seat.state_seq > best.state_seq:
                best = seat
        return best if best is not None else (self._host() if self.seats else None)

    async def _any_state_update(self, timeout_s: float) -> bool:
        waiters = [
            asyncio.create_task(seat.wait_for_state(timeout_s))
            for seat in self.seats.values()
        ]
        if not waiters:
            await asyncio.sleep(timeout_s)
            return False
        try:
            done, _ = await asyncio.wait(
                waiters, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for task in waiters:
                task.cancel()
        return any(task.result() for task in done if not task.cancelled())

    async def _wait_for_stop(self) -> None:
        while not self._should_stop():
            await asyncio.sleep(0.2)

    def _ledger_status(self, status: str) -> None:
        if self.ledger is not None:
            try:
                self.ledger.set_status(self.session_id, status)
            except Exception:  # noqa: BLE001
                logger.exception("ledger status update failed")

    async def _log(
        self, level: str, message: str, phase: str = "", player: str = "system"
    ) -> None:
        getattr(logger, level if level != "warning" else "warning", logger.info)(
            "[%s] %s", player, message
        )
        await self._emit(
            {
                "type": "log",
                "level": level,
                "message": message,
                "phase": phase,
                "player": player,
            }
        )

    def _emit_nowait(self, event: Dict[str, Any]) -> None:
        if self.on_event is None:
            return
        try:
            result = self.on_event(event)
            if inspect.isawaitable(result):
                asyncio.ensure_future(result)
        except Exception:  # noqa: BLE001
            logger.exception("on_event callback failed")

    async def _emit(self, event: Dict[str, Any]) -> None:
        if self.on_event is None:
            return
        try:
            result = self.on_event(event)
            if inspect.isawaitable(result):
                await result
        except Exception:  # noqa: BLE001 — observers must not kill the game
            logger.exception("on_event callback failed")
