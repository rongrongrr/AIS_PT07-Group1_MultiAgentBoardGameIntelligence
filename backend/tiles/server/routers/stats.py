"""Dashboard statistics (docs/API.md "Stats")."""

from __future__ import annotations

from fastapi import APIRouter, Request

from tiles.server.stats import compute_stats

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("")
def stats(request: Request) -> dict:
    state = request.app.state.tiles
    return compute_stats(state.ledger, state.sessions.list())
