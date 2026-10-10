"""Profile analysis API routes."""

from __future__ import annotations

import json
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from tiles.ml.analyzers import analyzer_registry
from tiles.models.db import Move, Session, get_db
from tiles.models.schemas import GameAction

router = APIRouter()

PREFERRED_ANALYZERS = ("ArchetypeProfileAnalyzer", "BasicProfileAnalyzer")


def _load_moves(db: DBSession, session_id: str) -> List[dict]:
    """Ledger moves of a session in the flat shape the analyzers expect."""
    moves = db.query(Move).filter(Move.session_id == session_id).order_by(Move.step_id).all()
    out = []
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
        entry.update(extra)
        out.append(entry)
    return out


def _final_scores(session: Optional[Session]) -> Optional[dict]:
    """The recorded final scores of a completed session (None while it is running or was aborted)."""
    if session is not None and session.status == "completed" and session.final_scores:
        return json.loads(session.final_scores)
    return None


def _insight(analyzer_name: str, player: str, moves: List[dict], final_scores: Optional[dict] = None) -> dict:
    analyzer = analyzer_registry.get(analyzer_name)
    profile = analyzer.analyze(player, moves, final_scores)
    return {
        "player_name": player,
        "analyzer": analyzer_name,
        "moves_observed": sum(1 for m in moves if m.get("player_name") == player),
        "style": profile.get("style"),
        "archetype": profile.get("archetype"),
        "archetype_confidence": profile.get("archetype_confidence"),
        "archetype_reasons": profile.get("archetype_reasons", []),
        "summary": profile.get("summary", ""),
    }


def _default_analyzer(requested: Optional[str]) -> str:
    if requested:
        if analyzer_registry.get(requested) is None:
            names = [a["name"] for a in analyzer_registry.list_all()]
            raise HTTPException(status_code=400, detail=f"Analyzer '{requested}' not found. Available: {names}")
        return requested
    return next(n for n in PREFERRED_ANALYZERS if analyzer_registry.get(n))


@router.get("/{session_id}/insights")
def session_insights(session_id: str, analyzer_name: Optional[str] = None, upto_step: Optional[int] = None,
                     db: DBSession = Depends(get_db)):
    """Profiler insights for every player of a session (usable mid-game: it reads the ledger so far).

    ``upto_step`` limits the profile to moves up to that step, which is how the replay overlays the
    profile as it stood at each point of the game.
    """
    session = db.query(Session).filter(Session.id == session_id).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    name = _default_analyzer(analyzer_name)
    moves = _load_moves(db, session_id)
    final = _final_scores(session)
    if upto_step is not None:
        moves = [m for m in moves if m["step_id"] <= upto_step]
        final = None                       # a profile "as of move N" must not use the end-of-game score
    players = list(dict.fromkeys(m["player_name"] for m in moves))
    return {"session_id": session_id, "analyzer": name, "total_moves": len(moves),
            "insights": [_insight(name, p, moves, final) for p in players]}


# ---- external ingestion: push move records from any source and get a running profile back ----

_streams: Dict[str, List[dict]] = {}
MAX_STREAMS = 100
MAX_MOVES_PER_STREAM = 5000


class IngestMove(BaseModel):
    stream_id: str = Field(min_length=1, max_length=64)
    player_name: str = Field(min_length=1, max_length=64)
    action: GameAction
    decision_time_ms: Optional[int] = None
    board: Optional[dict] = None          # ledger-format pre-move board; enables the learned archetype
    analyzer_name: Optional[str] = None


@router.post("/ingest")
def ingest_move(req: IngestMove):
    """Push one move record to the profiling agent and receive the player's running profile.

    Records are kept in memory per ``stream_id`` (bounded), so an external platform or log replayer
    can profile players without a TILES session.
    """
    if req.stream_id not in _streams and len(_streams) >= MAX_STREAMS:
        _streams.pop(next(iter(_streams)))
    moves = _streams.setdefault(req.stream_id, [])
    if len(moves) >= MAX_MOVES_PER_STREAM:
        raise HTTPException(status_code=413, detail="Stream is full")
    entry = {"step_id": len(moves) + 1, "player_name": req.player_name,
             "action": req.action.model_dump(mode="json"), "decision_time_ms": req.decision_time_ms}
    if req.board:
        entry["board"] = req.board
    moves.append(entry)
    name = _default_analyzer(req.analyzer_name)
    return {"stream_id": req.stream_id, "step_id": entry["step_id"], "insight": _insight(name, req.player_name, moves)}


@router.get("/stream/{stream_id}/insights")
def stream_insights(stream_id: str, analyzer_name: Optional[str] = None):
    moves = _streams.get(stream_id)
    if moves is None:
        raise HTTPException(status_code=404, detail="Stream not found")
    name = _default_analyzer(analyzer_name)
    players = list(dict.fromkeys(m["player_name"] for m in moves))
    return {"stream_id": stream_id, "analyzer": name, "total_moves": len(moves),
            "insights": [_insight(name, p, moves) for p in players]}


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

    move_list = _load_moves(db, session_id)

    profile = analyzer.analyze(player_name, move_list, _final_scores(session))
    profile["analyzer"] = analyzer_name
    profile["session_id"] = session_id

    return profile
