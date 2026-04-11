"""Pydantic schemas for TILES API and internal data structures."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# --- Enums ---

class TileColor(str, Enum):
    BLUE = "blue"
    YELLOW = "yellow"
    RED = "red"
    BLACK = "black"
    WHITE = "white"

    @classmethod
    def all_colors(cls) -> list:
        return list(cls)


class SourceType(str, Enum):
    FACTORY = "factory"
    CENTER = "center"


class DestinationType(str, Enum):
    PATTERN_LINE = "pattern_line"
    FLOOR = "floor"


class SessionStatus(str, Enum):
    CREATED = "created"
    LOBBY = "lobby"
    PLAYING = "playing"
    COMPLETED = "completed"
    ABORTED = "aborted"


class BrowserMode(str, Enum):
    HEADLESS = "headless"
    HEADED = "headed"


# --- Game Data Structures ---

class PlayerState(BaseModel):
    index: int
    name: str
    system_tag: Optional[str] = None
    score: int = 0
    pattern_lines: List[List[Optional[TileColor]]] = Field(
        default_factory=lambda: [[] for _ in range(5)]
    )
    wall: List[List[bool]] = Field(
        default_factory=lambda: [[False] * 5 for _ in range(5)]
    )
    floor_line: List[TileColor] = Field(default_factory=list)
    has_first_player_token: bool = False


class GameStateData(BaseModel):
    """Parsed game state from the Azul platform."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    session_id: Optional[str] = None
    room_name: str = ""
    round: int = 1
    current_turn: str = ""
    factories: List[List[TileColor]] = Field(default_factory=list)
    center_pool: List[str] = Field(default_factory=list)  # includes "firstPlayer"
    players: List[PlayerState] = Field(default_factory=list)
    game_over: bool = False


class GameAction(BaseModel):
    """An action a player can take in Azul."""
    source_type: SourceType
    source_index: Optional[int] = None  # factory index, None for center
    color: TileColor
    destination: DestinationType
    destination_row: Optional[int] = None  # 0-4 for pattern lines, None for floor


class MoveRecord(BaseModel):
    """A recorded move in the game ledger."""
    session_id: str
    step_id: int
    player_name: str
    system_tag: Optional[str] = None
    action: GameAction
    game_state_before: Optional[GameStateData] = None
    game_state_after: Optional[GameStateData] = None
    decision_time_ms: Optional[int] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# --- API Request/Response Schemas ---

class PlayerSlotConfig(BaseModel):
    slot: int  # 0-3
    type: str  # "human" or a machine player model id
    name: Optional[str] = None


class ProfilerConfig(BaseModel):
    profiler_id: Optional[str] = None
    target_players: List[int] = Field(default_factory=list)  # slot indices to profile


class SessionCreate(BaseModel):
    room_name: str
    platform_url: str = "https://buddyboardgames.com/azul"
    browser_mode: BrowserMode = BrowserMode.HEADLESS
    players: List[PlayerSlotConfig]
    profiler: Optional[ProfilerConfig] = None
    move_timeout_sec: int = 10  # max seconds per move decision + execution
    stuck_abort_sec: int = 3    # abort session N sec after timeout with no progress


class SessionResponse(BaseModel):
    id: str
    room_name: str
    platform_url: str
    browser_mode: BrowserMode
    status: SessionStatus
    player_config: List[PlayerSlotConfig]
    profiler_config: Optional[ProfilerConfig] = None
    move_timeout_sec: int = 10
    stuck_abort_sec: int = 3
    final_scores: Optional[dict] = None
    winner: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class SessionStatusUpdate(BaseModel):
    status: SessionStatus


class MLModelRegister(BaseModel):
    name: str
    model_type: str  # player | profiler | unified
    config: Optional[dict] = None


class MLModelResponse(BaseModel):
    id: str
    name: str
    model_type: str
    config: Optional[dict] = None
    registered_at: datetime


class MoveResponse(BaseModel):
    step_id: int
    player_name: str
    system_tag: Optional[str] = None
    action: GameAction
    decision_time_ms: Optional[int] = None
    timestamp: datetime


class GameHistoryResponse(BaseModel):
    session_id: str
    room_name: str
    total_moves: int
    moves: List[MoveResponse]
