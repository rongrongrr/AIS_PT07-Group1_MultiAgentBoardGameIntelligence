"""Session lifecycle + WebSocket stream (docs/API.md "Sessions")."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from tiles.server.schemas import SessionCreate
from tiles.server.sessions import SessionError

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _manager(request: Request):
    return request.app.state.tiles.sessions


def _raise(exc: SessionError) -> None:
    raise HTTPException(exc.status_code, exc.detail)


@router.post("", status_code=201)
def create_session(config: SessionCreate, request: Request) -> dict:
    try:
        session = _manager(request).create(config)
    except SessionError as exc:
        _raise(exc)
    return session.detail()


@router.get("")
def list_sessions(request: Request) -> list:
    return _manager(request).list()


@router.get("/{session_id}")
def get_session(session_id: str, request: Request) -> dict:
    detail = _manager(request).detail(session_id)
    if detail is None:
        raise HTTPException(404, "session not found")
    return detail


@router.post("/{session_id}/start")
def start_session(session_id: str, request: Request) -> dict:
    manager = _manager(request)
    try:
        manager.start(manager.require(session_id))
    except SessionError as exc:
        _raise(exc)
    return {"status": "running"}


@router.post("/{session_id}/stop")
def stop_session(session_id: str, request: Request) -> dict:
    manager = _manager(request)
    try:
        manager.stop(manager.require(session_id))
    except SessionError as exc:
        _raise(exc)
    return {"status": "aborting"}


@router.delete("/{session_id}")
def delete_session(session_id: str, request: Request) -> dict:
    try:
        _manager(request).delete(session_id)
    except SessionError as exc:
        _raise(exc)
    return {"deleted": session_id}


@router.websocket("/{session_id}/ws")
async def session_ws(websocket: WebSocket, session_id: str) -> None:
    manager = websocket.app.state.tiles.sessions
    session = manager.get(session_id)
    if session is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    queue: asyncio.Queue = asyncio.Queue()
    # Replay buffered events so late subscribers catch up.
    for event in list(session.events):
        await websocket.send_json(event)
    session.subscribers.append(queue)
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        if queue in session.subscribers:
            session.subscribers.remove(queue)
