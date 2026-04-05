"""Game history and replay API routes."""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session as DBSession

from app.models.db import GameState, Move, Session, get_db
from app.models.schemas import GameAction, GameHistoryResponse, MoveResponse

router = APIRouter()


@router.get("/{session_id}")
def get_history(session_id: str, db: DBSession = Depends(get_db)):
    """Get the full move history for a session."""
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    moves = (
        db.query(Move)
        .filter(Move.session_id == session_id)
        .order_by(Move.step_id)
        .all()
    )

    move_responses = []
    for m in moves:
        action_data = json.loads(m.action_json)
        extra = action_data.pop("_extra", {})
        action = GameAction(**action_data)
        resp = {
            "step_id": m.step_id,
            "player_name": m.player_name,
            "system_tag": m.system_tag,
            "action": action.model_dump(),
            "decision_time_ms": m.decision_time_ms,
            "timestamp": m.timestamp.isoformat() if m.timestamp else None,
        }
        # Merge extra fields (board, scores, round, timing)
        if extra:
            resp.update(extra)
        move_responses.append(resp)

    return {
        "session_id": session_id,
        "room_name": session.room_name,
        "total_moves": len(move_responses),
        "moves": move_responses,
    }


@router.get("/{session_id}/export")
def export_game(session_id: str, db: DBSession = Depends(get_db)):
    """Export a complete game as a single JSON document.

    Contains: session metadata, all moves with board snapshots,
    and final game state. Suitable for replay, analysis, or archival.
    """
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

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
        move_entry = {
            "step_id": m.step_id,
            "player_name": m.player_name,
            "system_tag": m.system_tag,
            "action": action_data,
            "decision_time_ms": m.decision_time_ms,
            "timestamp": m.timestamp.isoformat() if m.timestamp else None,
        }
        if extra:
            move_entry.update(extra)
        move_list.append(move_entry)

    # Group moves into rounds
    rounds = []
    current_round_moves = []
    current_round = 1
    prev_tiles = -1

    for m in move_list:
        total_tiles = -1
        if m.get("board"):
            ft = sum(len(f) for f in m["board"].get("factories", []))
            ct = len([t for t in m["board"].get("center_pool", []) if t != "firstPlayer"])
            total_tiles = ft + ct

        if prev_tiles >= 0 and total_tiles > prev_tiles + 5 and current_round_moves:
            last = current_round_moves[-1]
            rounds.append({
                "round": current_round,
                "moves": len(current_round_moves),
                "end_scores": last.get("scores", {}),
            })
            current_round_moves = []
            current_round += 1

        current_round_moves.append(m)
        if total_tiles >= 0:
            prev_tiles = total_tiles

    if current_round_moves:
        last = current_round_moves[-1]
        rounds.append({
            "round": current_round,
            "moves": len(current_round_moves),
            "end_scores": last.get("scores", {}),
        })

    return {
        "export_version": "1.0",
        "session": {
            "id": session.id,
            "room_name": session.room_name,
            "platform_url": session.platform_url,
            "browser_mode": session.browser_mode,
            "status": session.status,
            "player_config": json.loads(session.player_config),
            "move_timeout_sec": session.move_timeout_sec,
            "created_at": session.created_at.isoformat() if session.created_at else None,
            "completed_at": session.completed_at.isoformat() if session.completed_at else None,
        },
        "summary": {
            "total_moves": len(move_list),
            "total_rounds": len(rounds),
            "rounds": rounds,
            "final_scores": move_list[-1].get("scores", {}) if move_list else {},
        },
        "moves": move_list,
    }


@router.get("/{session_id}/state/{step_id}")
def get_state_at_step(session_id: str, step_id: int, db: DBSession = Depends(get_db)):
    """Get the game state at a specific step."""
    state = (
        db.query(GameState)
        .filter(GameState.session_id == session_id, GameState.step_id == step_id)
        .first()
    )
    if not state:
        raise HTTPException(status_code=404, detail="State not found for this step")

    return {
        "session_id": session_id,
        "step_id": step_id,
        "state": json.loads(state.state_json),
        "captured_at": state.captured_at.isoformat(),
    }


@router.get("/{session_id}/states")
def list_states(
    session_id: str,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    db: DBSession = Depends(get_db),
):
    """List available state snapshots for a session."""
    states = (
        db.query(GameState)
        .filter(GameState.session_id == session_id)
        .order_by(GameState.step_id)
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {
        "session_id": session_id,
        "states": [
            {
                "step_id": s.step_id,
                "captured_at": s.captured_at.isoformat(),
            }
            for s in states
        ],
    }
