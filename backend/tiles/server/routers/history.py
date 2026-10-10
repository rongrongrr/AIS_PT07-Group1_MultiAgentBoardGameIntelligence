"""History, replay and export (docs/API.md "History & replay")."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/{session_id}")
def history(session_id: str, request: Request) -> dict:
    state = request.app.state.tiles
    summary = state.sessions.summary(session_id)
    if summary is None:
        raise HTTPException(404, "session not found")
    return {
        "session": summary,
        "moves": state.ledger.get_history(session_id),
        "rounds": state.ledger.get_rounds(session_id),
    }


@router.get("/{session_id}/export")
def export(session_id: str, request: Request) -> JSONResponse:
    state = request.app.state.tiles
    if state.ledger.get_session(session_id) is None:
        raise HTTPException(404, "session not found")
    payload = state.ledger.export(session_id)
    payload["export_version"] = "2.0"
    payload["summary"] = state.sessions.summary(session_id)
    return JSONResponse(
        payload,
        headers={"Content-Disposition": f'attachment; filename="{session_id}.json"'},
    )
