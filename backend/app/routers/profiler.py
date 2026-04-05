"""Profile analysis API routes."""

from __future__ import annotations

import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from app.ml.analyzers import analyzer_registry
from app.models.db import Move, Session, get_db
from app.models.schemas import GameAction

router = APIRouter()


@router.get("/analyzers")
def list_analyzers():
    """List all available profile analyzers."""
    return {"analyzers": analyzer_registry.list_all()}


@router.post("/{session_id}/analyze")
def analyze_player(
    session_id: str,
    player_name: str,
    analyzer_name: str = "BasicProfileAnalyzer",
    db: DBSession = Depends(get_db),
):
    """Analyze a player's behavior in a session."""
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    analyzer = analyzer_registry.get(analyzer_name)
    if not analyzer:
        available = [a["name"] for a in analyzer_registry.list_all()]
        raise HTTPException(
            status_code=400,
            detail=f"Analyzer '{analyzer_name}' not found. Available: {available}",
        )

    # Load all moves
    moves = (
        db.query(Move)
        .filter(Move.session_id == session_id)
        .order_by(Move.step_id)
        .all()
    )

    move_list = []
    for m in moves:
        action_data = json.loads(m.action_json)
        extra = action_data.pop("_extra", {})
        entry = {
            "step_id": m.step_id,
            "player_name": m.player_name,
            "system_tag": m.system_tag,
            "action": action_data,
            "decision_time_ms": m.decision_time_ms,
        }
        if extra:
            entry.update(extra)
        move_list.append(entry)

    profile = analyzer.analyze(player_name, move_list)
    profile["analyzer"] = analyzer_name
    profile["session_id"] = session_id

    return profile
