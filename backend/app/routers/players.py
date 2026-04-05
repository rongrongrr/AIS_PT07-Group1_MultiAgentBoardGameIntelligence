"""Machine Player management API routes."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter

from app.ml.registry import registry

router = APIRouter()


@router.get("")
def list_players():
    """List all registered Machine Players."""
    return {
        "players": registry.list_players(),
        "profilers": registry.list_profilers(),
    }


@router.get("/{name}")
def get_player(name: str):
    """Get details of a specific Machine Player."""
    player = registry.get_player(name)
    if not player:
        profiler = registry.get_profiler(name)
        if not profiler:
            return {"error": f"Model '{name}' not found"}
        return {"name": profiler.name, "type": "profiler"}
    return {"name": player.name, "type": "player"}
