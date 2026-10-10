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


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from tiles.models.db import SessionLocal
    from tiles.routers.players import load_registered_players

    db = SessionLocal()
    try:
        load_registered_players(db)       # remote players registered in earlier runs
    finally:
        db.close()
    yield


app = FastAPI(
    title="TILES",
    description="AI-driven platform for Azul board game automation and player profiling",
    version="0.1.0",
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
    the key in the ``X-API-Key`` header. WebSockets are checked separately (see ``ws_guard``)."""
    path = request.url.path
    if path.startswith("/api/") and path != "/api/health" and not api_key_ok(request.headers.get("x-api-key")):
        return JSONResponse({"detail": "Missing or invalid API key"}, status_code=401)
    return await call_next(request)


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "tiles"}


# Optional single-process mode: serve the built React UI (``npm run build`` -> frontend/dist) from the
# API itself. Docker Compose uses nginx for this instead; this is for ``tiles serve`` without Docker.
_ui_dist = os.environ.get("TILES_UI_DIST")
if _ui_dist and os.path.isdir(_ui_dist):
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app.mount("/assets", StaticFiles(directory=os.path.join(_ui_dist, "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        candidate = os.path.join(_ui_dist, path)
        if path and os.path.isfile(candidate) and os.path.abspath(candidate).startswith(os.path.abspath(_ui_dist)):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_ui_dist, "index.html"))
