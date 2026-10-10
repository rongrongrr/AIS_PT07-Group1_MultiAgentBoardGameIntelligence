"""Session lifecycle: local matches and live games behind one manager.

A ``ManagedSession`` is the in-memory view of a running (or recently
run) session; the ledger is the durable one. Both local matches (the
``MatchRunner`` on a worker thread) and live games (``LiveSession`` on
its own asyncio loop in a worker thread) report through the same
``publish`` path, so WebSocket subscribers and the ledger see identical
event shapes regardless of mode (docs/API.md).
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from tiles.agents.explainer import EXPLAINERS
from tiles.agents.profiler import PROFILERS
from tiles.agents.tacticians import TACTICIANS, make_tactician
from tiles.engine.protocol import room_link
from tiles.ledger.store import Ledger

from .schemas import SessionCreate

EVENT_BUFFER = 500
#: Finished sessions kept in memory (their events stay replayable); older
#: ones are dropped and served from the ledger instead.
MAX_FINISHED_IN_MEMORY = 20
_TERMINAL = ("completed", "aborted", "failed", "stalled")


class SessionError(Exception):
    """Raised by the manager for API-mappable failures."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _validate_tactician_config(name: str, tactician: str, config: dict) -> None:
    """Reject unknown or out-of-range Tactician settings up front, so a
    bad config is a 422 here rather than a failed game later."""
    from tiles.agents.catalog import TACTICIAN_INFO

    for param in TACTICIAN_INFO.get(tactician, {}).get("params", []):
        if param["name"] not in config or config[param["name"]] is None:
            continue
        value = config[param["name"]]
        numeric = (int,) if param["type"] == "int" else (int, float)
        if isinstance(value, bool) or not isinstance(value, numeric):
            raise SessionError(
                422, f"{name}: {param['name']} must be of type {param['type']}"
            )
        low, high = param.get("min"), param.get("max")
        if (low is not None and value < low) or (high is not None and value > high):
            raise SessionError(
                422, f"{name}: {param['name']} must be between {low} and {high}"
            )
    try:
        make_tactician(tactician, **config)
    except (TypeError, ValueError) as exc:
        raise SessionError(422, f"{name}: invalid {tactician} config ({exc})") from None


def validate_session_config(config: SessionCreate) -> None:
    if config.mode not in ("local", "live"):
        raise SessionError(422, "mode must be 'local' or 'live'")
    if not (2 <= len(config.players) <= 4):
        raise SessionError(422, "need 2-4 players")
    if config.mode == "live" and config.live is None:
        raise SessionError(422, "live config required for live mode")
    names = [p.name.strip() for p in config.players]
    if any(not n for n in names):
        raise SessionError(422, "every player needs a name")
    if len(set(names)) != len(names):
        raise SessionError(422, "player names must be unique")
    bots = 0
    for p in config.players:
        if p.tactician == "human":
            if config.mode != "live":
                raise SessionError(422, "human players require live mode")
        elif p.tactician not in TACTICIANS:
            raise SessionError(422, f"unknown tactician {p.tactician!r}")
        else:
            _validate_tactician_config(p.name, p.tactician, p.config)
            bots += 1
    if bots == 0:
        raise SessionError(422, "at least one machine player is required")
    if config.profiler and config.profiler not in PROFILERS:
        raise SessionError(422, f"unknown profiler {config.profiler!r}")
    if config.explainer and config.explainer not in EXPLAINERS:
        raise SessionError(422, f"unknown explainer {config.explainer!r}")
    if config.mode == "live" and config.live and not config.live.room_name.strip():
        raise SessionError(422, "live mode needs a room name")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ManagedSession:
    def __init__(self, session_id: str, config: SessionCreate) -> None:
        self.id = session_id
        self.config = config
        self.status = "created"
        self.result: Optional[dict] = None
        self.latest_state: Optional[dict] = None
        self.events: List[dict] = []
        self.subscribers: List[asyncio.Queue] = []
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        # Known up front so the UI can show the share link immediately.
        self.room_url: Optional[str] = (
            room_link(config.live.platform_url, config.live.room_name)
            if config.live is not None
            else None
        )
        self.error: Optional[str] = None
        self.created_at = _now()
        self.completed_at: Optional[str] = None
        self.steps = 0
        self.scores: Optional[List[int]] = None
        self.winner: Optional[int] = None

    @property
    def is_running(self) -> bool:
        return self.status not in ("created",) + _TERMINAL

    def summary(self) -> dict:
        players = [p.model_dump() for p in self.config.players]
        winner_name = (
            players[self.winner]["name"]
            if self.winner is not None and 0 <= self.winner < len(players)
            else None
        )
        return {
            "id": self.id,
            "mode": self.config.mode,
            "status": self.status,
            "players": players,
            "profiler": self.config.profiler,
            "explainer": self.config.explainer,
            "seed": self.config.seed,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "scores": self.scores,
            "winner": self.winner,
            "winner_name": winner_name,
            "steps": self.steps,
            "rounds": (self.latest_state or {}).get("round"),
            "room_url": self.room_url,
            "room_name": self.config.live.room_name if self.config.live else None,
        }

    def detail(self) -> dict:
        out = self.summary()
        out.update(
            {
                "state": self.latest_state,
                "result": self.result,
                "move_delay_ms": self.config.move_delay_ms,
                "live": self.config.live.model_dump() if self.config.live else None,
                "error": self.error,
            }
        )
        return out


def summary_from_row(row: dict, steps: Optional[int] = None) -> dict:
    """SessionSummary from a ledger row (sessions that are not in memory)."""
    config = row.get("config") or {}
    result = row.get("result") or {}
    players = config.get("players") or []
    winner = result.get("winner")
    winner_name = result.get("winner_name")
    if winner_name is None and winner is not None and 0 <= winner < len(players):
        winner_name = players[winner].get("name")
    live = config.get("live") or {}
    room_url = None
    if row.get("mode") == "live" and live.get("room_name"):
        room_url = room_link(live.get("platform_url", ""), live["room_name"])
    return {
        "id": row["id"],
        "mode": row.get("mode", "local"),
        "status": row.get("status", "created"),
        "players": players,
        "profiler": config.get("profiler"),
        "explainer": config.get("explainer"),
        "seed": config.get("seed"),
        "created_at": row.get("created_at"),
        "completed_at": row.get("completed_at"),
        "scores": result.get("scores"),
        "winner": winner,
        "winner_name": winner_name,
        "steps": result.get("steps", steps if steps is not None else 0),
        "rounds": result.get("rounds"),
        "room_url": room_url,
        "room_name": live.get("room_name") if row.get("mode") == "live" else None,
    }


class SessionManager:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self.sessions: Dict[str, ManagedSession] = {}
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        # Guards each session's event buffer and subscriber list together,
        # so a new subscriber neither misses nor duplicates an event.
        self._lock = threading.Lock()

    # -- event fan-out (called from worker threads) ----------------------------

    def subscribe(self, session: ManagedSession) -> asyncio.Queue:
        """Queue pre-filled with the buffered events and registered for
        new ones, atomically with respect to ``publish``."""
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            for event in session.events:
                queue.put_nowait(event)
            session.subscribers.append(queue)
        return queue

    def unsubscribe(self, session: ManagedSession, queue: asyncio.Queue) -> None:
        with self._lock:
            if queue in session.subscribers:
                session.subscribers.remove(queue)

    def publish(self, session: ManagedSession, event: dict) -> None:
        kind = event.get("type")
        if kind == "state":
            session.latest_state = event.get("state")
        elif kind == "move":
            record = event.get("record", {})
            session.latest_state = record.get("state_after") or session.latest_state
            session.steps = max(session.steps, int(record.get("step", 0)))
        elif kind == "game_over":
            session.scores = event.get("scores")
            session.winner = event.get("winner")
        elif kind == "status":
            if event.get("room_url"):
                session.room_url = event["room_url"]
            status = event.get("status")
            if status and status != session.status:
                session.status = status
                if status in _TERMINAL:
                    session.completed_at = _now()
        elif kind == "log" and event.get("level") == "error":
            session.error = event.get("message")
        with self._lock:
            session.events.append(event)
            if len(session.events) > EVENT_BUFFER:
                del session.events[: len(session.events) - EVENT_BUFFER]
            queues = list(session.subscribers)
        if self.loop is not None:
            for queue in queues:
                try:
                    self.loop.call_soon_threadsafe(queue.put_nowait, event)
                except RuntimeError:  # loop closed
                    pass
        if kind == "status" and session.status in _TERMINAL:
            self._evict_finished()

    def _evict_finished(self) -> None:
        """Drop the oldest finished sessions beyond the in-memory cap;
        the ledger still has everything they recorded."""
        finished = [
            s for s in list(self.sessions.values())
            if s.status in _TERMINAL and not s.subscribers
        ]
        finished.sort(key=lambda s: s.completed_at or "")
        for session in finished[: max(0, len(finished) - MAX_FINISHED_IN_MEMORY)]:
            self.sessions.pop(session.id, None)

    def set_status(self, session: ManagedSession, status: str) -> None:
        try:
            self.ledger.set_status(session.id, status)
        except Exception:  # noqa: BLE001 — the ledger must never kill the game
            pass
        self.publish(session, {"type": "status", "status": status})

    # -- workers ---------------------------------------------------------------

    def _run_local(self, session: ManagedSession) -> None:
        from tiles.sim.match import MatchConfig, MatchRunner

        config = MatchConfig(
            players=[p.model_dump() for p in session.config.players],
            profiler=session.config.profiler,
            explainer=session.config.explainer,
            seed=session.config.seed,
            move_delay_ms=session.config.move_delay_ms,
        )
        try:
            self.set_status(session, "running")
            match = MatchRunner(
                config,
                ledger=self.ledger,
                on_event=lambda event: self.publish(session, event),
                session_id=session.id,
                stop_check=session.stop_event.is_set,
            ).run()
            session.result = {
                "scores": match.scores,
                "winner": match.winner,
                "winner_name": match.winner_name,
                "steps": match.steps,
                "rounds": match.rounds,
                "duration_s": round(match.duration_s, 2),
            }
            session.steps = match.steps
            if not session.stop_event.is_set():
                session.scores = match.scores
                session.winner = match.winner
            self.set_status(
                session,
                "aborted" if session.stop_event.is_set() else "completed",
            )
        except Exception as exc:  # surface, don't kill the server
            self.publish(
                session,
                {"type": "log", "level": "error", "message": str(exc),
                 "phase": "session", "player": "system"},
            )
            self.set_status(session, "failed")

    def _run_live(self, session: ManagedSession) -> None:
        try:
            from tiles.engine.live_session import LiveSession  # noqa: F401
            import playwright  # noqa: F401
        except ImportError as exc:
            self.publish(
                session,
                {"type": "log", "level": "error", "phase": "session",
                 "player": "system",
                 "message": f"live mode unavailable: {exc}. Install with "
                            "pip install 'tiles[live]' && playwright install chromium"},
            )
            self.set_status(session, "failed")
            return
        try:
            summary = asyncio.run(self._live_coroutine(session))
            session.result = {
                k: summary.get(k)
                for k in ("scores", "winner", "winner_name", "steps", "rounds")
            }
            status = summary.get("status", "completed")
            if status == "completed":
                session.scores = summary.get("scores")
                session.winner = summary.get("winner")
            self.set_status(session, status)
        except Exception as exc:
            if session.error != str(exc):  # LiveSession may have logged it already
                self.publish(
                    session,
                    {"type": "log", "level": "error", "message": str(exc),
                     "phase": "session", "player": "system"},
                )
            self.set_status(
                session,
                "aborted" if session.stop_event.is_set() else "failed",
            )

    async def _live_coroutine(self, session: ManagedSession) -> dict:
        from tiles.agents.explainer import make_explainer
        from tiles.agents.profiler import make_profiler
        from tiles.engine.live_session import (
            LiveSeat,
            LiveSession,
            LiveSessionConfig,
        )

        live = session.config.live
        seats = []
        for p in session.config.players:
            tactician = (
                None if p.tactician == "human" else make_tactician(p.tactician, **p.config)
            )
            seats.append(LiveSeat(name=p.name, tactician=tactician))
        config = LiveSessionConfig(
            room_name=live.room_name,
            seats=seats,
            platform_url=live.platform_url,
            headless=live.headless,
            move_delay_ms=session.config.move_delay_ms,
        )
        runner = LiveSession(
            config,
            on_event=lambda e: self.publish(session, e),
            profiler=make_profiler(session.config.profiler)
            if session.config.profiler
            else None,
            explainer=make_explainer(session.config.explainer)
            if session.config.explainer
            else None,
            ledger=self.ledger,
            session_id=session.id,
            stop_event=session.stop_event,
        )
        return await runner.run()

    # -- API operations ------------------------------------------------------

    def create(self, config: SessionCreate) -> ManagedSession:
        validate_session_config(config)
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        session = ManagedSession(session_id, config)
        self.sessions[session_id] = session
        self.ledger.create_session(
            session_id,
            mode=config.mode,
            config=config.model_dump(),
        )
        return session

    def start(self, session: ManagedSession) -> None:
        if session.status != "created":
            raise SessionError(409, f"session is {session.status}")
        target = self._run_live if session.config.mode == "live" else self._run_local
        session.status = "starting"
        session.thread = threading.Thread(
            target=target, args=(session,), daemon=True, name=f"tiles-{session.id}"
        )
        session.thread.start()

    def stop(self, session: ManagedSession) -> None:
        session.stop_event.set()

    def get(self, session_id: str) -> Optional[ManagedSession]:
        return self.sessions.get(session_id)

    def require(self, session_id: str) -> ManagedSession:
        session = self.sessions.get(session_id)
        if session is None:
            raise SessionError(404, "session not found")
        return session

    def summary(self, session_id: str) -> Optional[dict]:
        session = self.sessions.get(session_id)
        if session is not None:
            return session.summary()
        row = self.ledger.get_session(session_id)
        if row is None:
            return None
        return summary_from_row(row, steps=self.ledger.count_moves(session_id))

    def detail(self, session_id: str) -> Optional[dict]:
        session = self.sessions.get(session_id)
        if session is not None:
            return session.detail()
        row = self.ledger.get_session(session_id)
        if row is None:
            return None
        history = self.ledger.get_history(session_id)
        last = history[-1] if history else None
        out = summary_from_row(row, steps=len(history))
        config = row.get("config") or {}
        out.update(
            {
                "state": (last or {}).get("state_after") if last else None,
                "result": row.get("result"),
                "move_delay_ms": config.get("move_delay_ms", 0),
                "live": config.get("live"),
                "error": None,
            }
        )
        return out

    def list(self) -> List[dict]:
        out: List[dict] = []
        seen = set()
        for row in self.ledger.list_sessions():
            live = self.sessions.get(row["id"])
            out.append(live.summary() if live else summary_from_row(row))
            seen.add(row["id"])
        # list(): worker threads may evict finished sessions concurrently.
        out.extend(s.summary() for sid, s in list(self.sessions.items()) if sid not in seen)
        out.sort(key=lambda s: s.get("created_at") or "", reverse=True)
        return out

    def delete(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session is not None:
            if session.is_running:
                raise SessionError(409, "stop the session before deleting it")
            del self.sessions[session_id]
        if not self.ledger.delete_session(session_id) and session is None:
            raise SessionError(404, "session not found")

    def shutdown(self) -> None:
        for session in list(self.sessions.values()):
            session.stop_event.set()
