"""Leaderboard: the latest saved round-robin Elo results (scripts/elo_tournament.py --save)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()

RESULTS_PATH = Path(__file__).resolve().parents[2] / "models" / "elo_results.json"


@router.get("")
def latest_tournament():
    """Latest tournament results, or ``{"available": false}`` if none has been saved."""
    try:
        return {"available": True, **json.loads(RESULTS_PATH.read_text())}
    except (OSError, ValueError):
        return {"available": False}
