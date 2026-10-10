"""FastAPI application entry point for TILES."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from tiles.auth import api_key_ok
from tiles.models.db import init_db
from tiles.routers import feedback, history, players, profiler, sessions, tournament

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def _abort_orphaned_sessions(db) -> int:
    """Sessions still marked running when the server starts lost their browsers with the last process."""
    from datetime import datetime

    from tiles.models.db import Session
    from tiles.models.schemas import SessionStatus

    live = (SessionStatus.LOBBY.value, SessionStatus.PLAYING.value)
    rows = db.query(Session).filter(Session.status.in_(live)).all()
    for row in rows:
        row.status = SessionStatus.ABORTED.value
        row.completed_at = datetime.utcnow()
    db.commit()
    if rows:
        logging.getLogger(__name__).warning("Marked %d session(s) from a previous run as aborted", len(rows))
    return len(rows)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from tiles.models.db import SessionLocal
    from tiles.routers.players import load_registered_players

    db = SessionLocal()
    try:
        _abort_orphaned_sessions(db)
        load_registered_players(db)       # remote players registered in earlier runs
    finally:
        db.close()
    yield


app = FastAPI(
    title="TILES",
    description="AI-driven platform for Azul board game automation and player profiling",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router, prefix="/api/sessions", tags=["sessions"])
app.include_router(players.router, prefix="/api/players", tags=["players"])
app.include_router(players.action_router, prefix="/api/player", tags=["players"])
app.include_router(history.router, prefix="/api/history", tags=["history"])
app.include_router(profiler.router, prefix="/api/profiler", tags=["profiler"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["feedback"])
app.include_router(tournament.router, prefix="/api/tournament", tags=["tournament"])


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    """Optional shared-secret auth: when TILES_API_KEY is set every /api call (except health) needs
    the key in the ``X-API-Key`` header. WebSockets are checked in ``routers.sessions.session_websocket``."""
    path = request.url.path
    if path.startswith("/api/") and path != "/api/health" and not api_key_ok(request.headers.get("x-api-key")):
        return JSONResponse({"detail": "Missing or invalid API key"}, status_code=401)
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "tiles"}


def mount_ui(application: FastAPI, dist: str) -> None:
    """Serve a built React UI (``npm run build`` -> frontend/dist) from the API itself.

    Single-process mode for ``tiles serve`` without Docker (set ``TILES_UI_DIST``); Docker Compose uses
    nginx for this. Unknown ``/api`` paths still return a JSON 404 rather than the UI page.
    """
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    root = os.path.abspath(dist)
    application.mount("/assets", StaticFiles(directory=os.path.join(root, "assets")), name="assets")

    @application.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        candidate = os.path.abspath(os.path.join(root, path))
        if path and candidate.startswith(root) and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(root, "index.html"))


_ui_dist = os.environ.get("TILES_UI_DIST")
if _ui_dist and os.path.isdir(_ui_dist):
    mount_ui(app, _ui_dist)
