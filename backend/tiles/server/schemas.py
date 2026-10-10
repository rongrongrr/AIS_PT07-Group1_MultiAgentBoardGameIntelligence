"""Pydantic request models for the API (docs/API.md)."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from tiles.engine.protocol import DEFAULT_PLATFORM_URL


class PlayerSpec(BaseModel):
    name: str
    tactician: str
    config: dict = Field(default_factory=dict)


class LiveSpec(BaseModel):
    room_name: str
    platform_url: str = DEFAULT_PLATFORM_URL
    headless: bool = True


class SessionCreate(BaseModel):
    mode: str = "local"  # "local" | "live"
    players: List[PlayerSpec]
    profiler: Optional[str] = "basic"
    explainer: Optional[str] = "template"
    seed: Optional[int] = None
    move_delay_ms: int = 0
    live: Optional[LiveSpec] = None
