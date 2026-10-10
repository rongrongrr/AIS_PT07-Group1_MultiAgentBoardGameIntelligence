"""TILES FastAPI server (app factory).

Wires the shared ``AppState`` (ledger, session manager, experiment
manager) and the per-area routers (docs/API.md). Local matches and live
games run on worker threads; events fan out to WebSocket subscribers
through the running event loop. When a frontend build exists at
``frontend/dist`` (or ``$TILES_UI_DIST``) it is served at ``/``.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from tiles.experiments.runner import ExperimentManager
from tiles.ledger.store import Ledger
from tiles.server.routers import (
    experiments,
    health,
    history,
    profiles,
    rulebook,
    sessions,
    stats,
)
from tiles.server.sessions import SessionManager
from tiles.server.state import VERSION, AppState


def create_app(db_path: str = "db/tiles.db") -> FastAPI:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(db_path)
    state = AppState(
        ledger=ledger,
        sessions=SessionManager(ledger),
        experiments=ExperimentManager(ledger),
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        loop = asyncio.get_running_loop()
        state.loop = loop
        state.sessions.loop = loop
        state.experiments.loop = loop
        yield
        state.sessions.shutdown()
        state.experiments.shutdown()

    app = FastAPI(title="TILES", version=VERSION, lifespan=lifespan)
    app.state.tiles = state
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(sessions.router)
    app.include_router(history.router)
    app.include_router(profiles.router)
    app.include_router(rulebook.router)
    app.include_router(stats.router)
    app.include_router(experiments.router)

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
