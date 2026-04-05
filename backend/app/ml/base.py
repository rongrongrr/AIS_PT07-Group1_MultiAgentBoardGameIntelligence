"""Abstract base classes for Machine Players and Profiling Agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.models.schemas import GameAction, GameStateData, MoveRecord


class MachinePlayer(ABC):
    """Abstract base class for all Machine Players."""

    @abstractmethod
    async def decide(self, game_state: GameStateData, player_index: int) -> GameAction:
        """Given the current game state and player index, return the action to take."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this player model."""
        ...


class ProfilerAgent(ABC):
    """Abstract base class for all Profiling Agents."""

    @abstractmethod
    async def observe(self, move_record: MoveRecord) -> Optional[dict]:
        """Observe a move and optionally return an insight."""
        ...

    @abstractmethod
    async def summarize(self, session_id: str) -> dict:
        """Generate a behavioral profile summary for players in a session."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this profiler model."""
        ...
