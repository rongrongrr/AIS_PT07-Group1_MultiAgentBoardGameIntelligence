"""FastAPI application entry point for OppoProfile."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.models.db import init_db
from app.routers import history, players, profiler, sessions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="OppoProfile",
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
app.include_router(history.router, prefix="/api/history", tags=["history"])
app.include_router(profiler.router, prefix="/api/profiler", tags=["profiler"])


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "oppo-profile"}
