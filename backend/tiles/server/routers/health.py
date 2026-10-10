"""Health + agent registry endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from tiles.agents.catalog import agents_catalog
from tiles.server.state import VERSION, live_available, llm_available

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": VERSION,
        "live_available": live_available(),
        "llm_available": llm_available(),
    }


@router.get("/agents")
def agents() -> dict:
    return agents_catalog()


@router.get("/tacticians")
def tacticians() -> list:
    """Legacy flat list (kept for the CI smoke test and old clients)."""
    out = [
        {
            "name": t["name"],
            "uses_opponent_model": t["uses_opponent_model"],
            "class": t["class"],
            "description": t["description"],
        }
        for t in agents_catalog()["tacticians"]
    ]
    out.append(
        {
            "name": "human",
            "uses_opponent_model": False,
            "class": "Human (live mode only)",
            "description": "A person who joins the live room via the share link.",
        }
    )
    return out
