"""TILES FastAPI server.

Implements docs/API.md: session lifecycle, WebSocket live updates,
history/replay/export, profiles. Local matches run on a worker thread
(the MatchRunner is synchronous); events fan out to WebSocket
subscribers through the running event loop. When a frontend build
exists at ``frontend/dist`` it is served at ``/``.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from tiles.agents.tacticians import TACTICIANS, make_tactician
from tiles.ledger.store import Ledger

VERSION = "0.2.0"
EVENT_BUFFER = 500


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class PlayerSpec(BaseModel):
    name: str
    tactician: str
    config: dict = Field(default_factory=dict)


class LiveSpec(BaseModel):
    room_name: str
    platform_url: str = "https://buddyboardgames.com/azul"
    headless: bool = True


class SessionCreate(BaseModel):
    mode: str = "local"  # "local" | "live"
    players: List[PlayerSpec]
    profiler: Optional[str] = "basic"
    explainer: Optional[str] = "template"
    seed: Optional[int] = None
    move_delay_ms: int = 0
    live: Optional[LiveSpec] = None


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------


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

    def summary(self) -> dict:
        return {
            "id": self.id,
            "mode": self.config.mode,
            "status": self.status,
            "players": [p.model_dump() for p in self.config.players],
            "profiler": self.config.profiler,
            "explainer": self.config.explainer,
            "seed": self.config.seed,
            "result": self.result,
        }


class SessionManager:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger
        self.sessions: Dict[str, ManagedSession] = {}
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    # -- event fan-out (called from the worker thread) ----------------------

    def publish(self, session: ManagedSession, event: dict) -> None:
        session.events.append(event)
        if len(session.events) > EVENT_BUFFER:
            del session.events[: len(session.events) - EVENT_BUFFER]
        if event.get("type") == "state":
            session.latest_state = event.get("state")
        elif event.get("type") == "move":
            record = event.get("record", {})
            session.latest_state = record.get("state_after", session.latest_state)
        if self.loop is not None:
            for queue in list(session.subscribers):
                self.loop.call_soon_threadsafe(queue.put_nowait, event)

    def set_status(self, session: ManagedSession, status: str) -> None:
        session.status = status
        try:
            self.ledger.set_status(session.id, status)
        except Exception:
            pass
        self.publish(session, {"type": "status", "status": status})

    # -- the match worker ----------------------------------------------------

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
                "steps": match.steps,
                "duration_s": round(match.duration_s, 2),
            }
            self.set_status(
                session,
                "aborted" if session.stop_event.is_set() else "completed",
            )
        except Exception as exc:  # surface, don't kill the server
            self.publish(
                session,
                {"type": "log", "level": "error", "message": str(exc)},
            )
            self.set_status(session, "failed")

    def _run_live(self, session: ManagedSession) -> None:
        try:
            from tiles.engine.live_session import LiveSession  # noqa: F401
        except ImportError as exc:
            self.publish(
                session,
                {
                    "type": "log",
                    "level": "error",
                    "message": f"live mode unavailable: {exc}",
                },
            )
            self.set_status(session, "failed")
            return
        try:
            self.set_status(session, "running")
            asyncio.run(
                self._live_coroutine(session)
            )
            self.set_status(session, "completed")
        except Exception as exc:
            self.publish(
                session,
                {"type": "log", "level": "error", "message": str(exc)},
            )
            self.set_status(
                session,
                "aborted" if session.stop_event.is_set() else "failed",
            )

    async def _live_coroutine(self, session: ManagedSession) -> None:
        from tiles.engine.live_session import LiveSession

        live = session.config.live
        tacticians = {}
        for i, p in enumerate(session.config.players):
            if p.tactician != "human":
                tacticians[i] = make_tactician(p.tactician, **p.config)
        runner = LiveSession(
            room_name=live.room_name,
            platform_url=live.platform_url,
            headless=live.headless,
            player_names=[p.name for p in session.config.players],
            tacticians=tacticians,
            on_event=lambda e: self.publish(session, e),
            stop_event=session.stop_event,
        )
        await runner.run()

    # -- API operations ------------------------------------------------------

    def create(self, config: SessionCreate) -> ManagedSession:
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
        if session.status not in ("created",):
            raise HTTPException(409, f"session is {session.status}")
        target = (
            self._run_live if session.config.mode == "live" else self._run_local
        )
        session.thread = threading.Thread(
            target=target, args=(session,), daemon=True
        )
        session.thread.start()

    def get(self, session_id: str) -> ManagedSession:
        session = self.sessions.get(session_id)
        if session is None:
            raise HTTPException(404, "session not found")
        return session


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(db_path: str = "db/tiles.db") -> FastAPI:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(db_path)
    manager = SessionManager(ledger)
    app = FastAPI(title="TILES", version=VERSION)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    async def _capture_loop() -> None:
        manager.loop = asyncio.get_running_loop()

    # -- health / registry ---------------------------------------------------

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": VERSION}

    @app.get("/api/tacticians")
    def tacticians() -> list:
        out = []
        for name in sorted(TACTICIANS):
            try:
                described = make_tactician(name).describe()
                described["name"] = name  # registry key, not instance alias
                out.append(described)
            except Exception:
                out.append({"name": name, "uses_opponent_model": None})
        out.append(
            {
                "name": "human",
                "uses_opponent_model": False,
                "class": "Human (live mode only)",
            }
        )
        return out

    # -- sessions ------------------------------------------------------------

    @app.post("/api/sessions", status_code=201)
    def create_session(config: SessionCreate) -> dict:
        if config.mode not in ("local", "live"):
            raise HTTPException(422, "mode must be 'local' or 'live'")
        if not (2 <= len(config.players) <= 4):
            raise HTTPException(422, "need 2-4 players")
        if config.mode == "live" and config.live is None:
            raise HTTPException(422, "live config required for live mode")
        for p in config.players:
            if p.tactician == "human":
                if config.mode != "live":
                    raise HTTPException(
                        422, "human players require live mode"
                    )
            elif p.tactician not in TACTICIANS:
                raise HTTPException(422, f"unknown tactician {p.tactician!r}")
        session = manager.create(config)
        return session.summary()

    @app.get("/api/sessions")
    def list_sessions() -> list:
        live = {s.id: s.summary() for s in manager.sessions.values()}
        stored = ledger.list_sessions()
        out = []
        seen = set()
        for row in stored:
            if row["id"] in live:
                out.append(live[row["id"]])
            else:
                out.append(row)
            seen.add(row["id"])
        out.extend(v for k, v in live.items() if k not in seen)
        return out

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str) -> dict:
        try:
            session = manager.get(session_id)
        except HTTPException:
            stored = ledger.get_session(session_id)
            if stored is None:
                raise
            return stored
        detail = session.summary()
        detail["latest_state"] = session.latest_state
        return detail

    @app.post("/api/sessions/{session_id}/start")
    def start_session(session_id: str) -> dict:
        session = manager.get(session_id)
        manager.start(session)
        return {"status": "running"}

    @app.post("/api/sessions/{session_id}/stop")
    def stop_session(session_id: str) -> dict:
        session = manager.get(session_id)
        session.stop_event.set()
        return {"status": "aborting"}

    # -- websocket -----------------------------------------------------------

    @app.websocket("/api/sessions/{session_id}/ws")
    async def session_ws(websocket: WebSocket, session_id: str) -> None:
        session = manager.sessions.get(session_id)
        if session is None:
            await websocket.close(code=4404)
            return
        await websocket.accept()
        queue: asyncio.Queue = asyncio.Queue()
        # Replay buffered events so late subscribers catch up.
        for event in session.events:
            await websocket.send_json(event)
        session.subscribers.append(queue)
        try:
            while True:
                event = await queue.get()
                await websocket.send_json(event)
        except WebSocketDisconnect:
            pass
        finally:
            if queue in session.subscribers:
                session.subscribers.remove(queue)

    # -- history -------------------------------------------------------------

    @app.get("/api/history/{session_id}")
    def history(session_id: str) -> dict:
        stored = ledger.get_session(session_id)
        if stored is None:
            raise HTTPException(404, "session not found")
        return {"session": stored, "moves": ledger.get_history(session_id)}

    @app.get("/api/history/{session_id}/export")
    def export(session_id: str) -> JSONResponse:
        stored = ledger.get_session(session_id)
        if stored is None:
            raise HTTPException(404, "session not found")
        return JSONResponse(
            ledger.export(session_id),
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{session_id}.json"'
                )
            },
        )

    @app.get("/api/profiles/{session_id}")
    def profiles(session_id: str) -> dict:
        export_data = ledger.export(session_id)
        return {"profiles": export_data.get("profiles", [])}

    # -- static frontend -----------------------------------------------------

    import os

    dist = Path(
        os.environ.get(
            "TILES_UI_DIST",
            Path(__file__).resolve().parents[3] / "frontend" / "dist",
        )
    )
    if dist.is_dir():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=dist, html=True), name="ui")

    return app


app = create_app()
