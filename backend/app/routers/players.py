"""Machine Player management API routes, including external (remote) models."""

from __future__ import annotations

import json
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession

from app.azul.rules import get_legal_actions
from app.ml.registry import registry
from app.ml.remote_player import RemotePlayer
from app.models.db import MLModel, get_db
from app.models.schemas import GameAction, GameStateData

router = APIRouter()
action_router = APIRouter()      # mounted at /api/player (reference implementation of the remote-model contract)

BUILTIN = {"RandomPlayer", "GreedyPlayer", "ColorCollectorPlayer", "RusherPlayer", "RecklessPlayer", "BlockerPlayer",
           "AdaptivePlayer", "RolloutPlayer", "AdaptiveRolloutPlayer", "MinimaxPlayer", "ConditionedMinimaxPlayer",
           "MCTSPlayer", "ConditionedMCTSPlayer", "TDPlayer"}


class RegisterRemote(BaseModel):
    name: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
    url: str = Field(pattern=r"^https?://")
    timeout_sec: float = Field(default=8.0, gt=0, le=60)


def load_registered_players(db: DBSession) -> int:
    """Re-register remote players saved in the database (called at startup)."""
    n = 0
    for row in db.query(MLModel).filter(MLModel.model_type == "player").all():
        cfg = json.loads(row.config_json or "{}")
        if cfg.get("url"):
            registry.register_player(RemotePlayer(row.name, cfg["url"], cfg.get("timeout_sec", 8.0)))
            n += 1
    return n


@router.get("")
def list_players():
    """List all registered Machine Players."""
    return {
        "players": registry.list_players(),
        "profilers": registry.list_profilers(),
    }


@router.post("/register")
def register_remote_player(body: RegisterRemote, db: DBSession = Depends(get_db)):
    """Register an external HTTP model as a Machine Player (see app/ml/remote_player.py for the contract)."""
    if body.name in BUILTIN:
        raise HTTPException(status_code=409, detail=f"'{body.name}' is a built-in player")
    existing = db.query(MLModel).filter(MLModel.name == body.name).first()
    cfg = json.dumps({"url": body.url, "timeout_sec": body.timeout_sec})
    if existing:
        existing.config_json = cfg
    else:
        db.add(MLModel(id=f"mdl_{uuid.uuid4().hex[:10]}", name=body.name, model_type="player", config_json=cfg))
    db.commit()
    registry.register_player(RemotePlayer(body.name, body.url, body.timeout_sec))
    return {"name": body.name, "type": "player", "url": body.url}


@router.delete("/{name}")
def unregister_remote_player(name: str, db: DBSession = Depends(get_db)):
    row = db.query(MLModel).filter(MLModel.name == name).first()
    if name in BUILTIN or row is None:
        raise HTTPException(status_code=404, detail="No such registered remote player")
    db.delete(row)
    db.commit()
    registry.unregister_player(name)
    return {"deleted": name}


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


class ActionRequest(BaseModel):
    state: GameStateData
    player_index: int
    legal_actions: Optional[List[GameAction]] = None
    model: str = "GreedyPlayer"        # which built-in model answers (reference implementation)


@action_router.post("/action")
async def player_action(req: ActionRequest):
    """Reference implementation of the remote-model contract: receive a state, return an action.

    Point ``RemotePlayer`` at this endpoint (of this or another TILES instance) to test the integration.
    """
    model = registry.create_player(req.model)
    if model is None or isinstance(model, RemotePlayer):
        raise HTTPException(status_code=400, detail=f"Unknown or non-local model '{req.model}'")
    if not get_legal_actions(req.state, req.player_index):
        raise HTTPException(status_code=422, detail="No legal actions in this state")
    action = await model.decide(req.state, req.player_index)
    return {"action": action.model_dump(mode="json"), "model": model.name}
