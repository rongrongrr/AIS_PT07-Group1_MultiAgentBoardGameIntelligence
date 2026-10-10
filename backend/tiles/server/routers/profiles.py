"""Profiles and the post-hoc Profile Analyzer (docs/API.md "Profiles")."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from tiles.agents.profiler import ARCHETYPES, PROFILERS, make_profiler
from tiles.agents.profiler.analysis import analyze_session

router = APIRouter(prefix="/api/profiles", tags=["profiles"])


@router.get("/archetypes")
def archetypes() -> list:
    return [
        {"name": name, "description": spec["description"], "signature": spec["signature"]}
        for name, spec in ARCHETYPES.items()
    ]


@router.get("/{session_id}")
def profiles(session_id: str, request: Request) -> dict:
    state = request.app.state.tiles
    if state.sessions.summary(session_id) is None:
        raise HTTPException(404, "session not found")
    return {"profiles": state.ledger.get_profiles(session_id)}


@router.post("/{session_id}/analyze")
def analyze(
    session_id: str,
    request: Request,
    profiler: str = Query("basic"),
) -> dict:
    state = request.app.state.tiles
    summary = state.sessions.summary(session_id)
    if summary is None:
        raise HTTPException(404, "session not found")
    if profiler not in PROFILERS:
        raise HTTPException(422, f"unknown profiler {profiler!r}; available: {sorted(PROFILERS)}")
    records = state.ledger.get_history(session_id)
    players = summary.get("players") or []
    names = {i: p.get("name", f"player_{i}") for i, p in enumerate(players)}
    tacticians = {i: p.get("tactician") for i, p in enumerate(players)}
    result = analyze_session(
        records, make_profiler(profiler), player_names=names, tacticians=tacticians
    )
    return {"session_id": session_id, "profiler": profiler, **result}
