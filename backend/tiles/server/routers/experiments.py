"""Experiments API (docs/API.md § Experiments)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from tiles.experiments.registry import list_specs

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


class ExperimentCreate(BaseModel):
    kind: str
    params: dict = Field(default_factory=dict)


def _manager(request: Request):
    return request.app.state.tiles.experiments


@router.get("/types")
def experiment_types() -> list:
    return [spec.to_dict() for spec in list_specs()]


@router.post("", status_code=201)
def create_experiment(body: ExperimentCreate, request: Request) -> dict:
    try:
        return _manager(request).start(body.kind, body.params)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("")
def list_experiments(request: Request) -> list:
    return _manager(request).list()


@router.get("/{experiment_id}")
def get_experiment(experiment_id: str, request: Request) -> dict:
    run = _manager(request).get(experiment_id)
    if run is None:
        raise HTTPException(404, "experiment not found")
    return run


@router.post("/{experiment_id}/stop")
def stop_experiment(experiment_id: str, request: Request) -> dict:
    try:
        _manager(request).stop(experiment_id)
    except KeyError:
        raise HTTPException(404, "experiment not found") from None
    return {"status": "aborting"}


@router.delete("/{experiment_id}")
def delete_experiment(experiment_id: str, request: Request) -> dict:
    manager = _manager(request)
    try:
        deleted = manager.delete(experiment_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None
    if not deleted:
        raise HTTPException(404, "experiment not found")
    return {"deleted": experiment_id}


@router.websocket("/{experiment_id}/ws")
async def experiment_ws(websocket: WebSocket, experiment_id: str) -> None:
    manager = websocket.app.state.tiles.experiments
    if manager.get(experiment_id) is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    # subscribe() pre-fills the queue with buffered history, atomically
    # with the subscription, so late subscribers catch up without gaps.
    queue = manager.subscribe(experiment_id)
    try:
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        manager.unsubscribe(experiment_id, queue)
