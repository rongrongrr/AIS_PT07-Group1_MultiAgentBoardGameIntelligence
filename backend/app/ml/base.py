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

    def clone(self) -> "MachinePlayer":
        """A fresh instance for one game (per-game state must not be shared between sessions)."""
        return type(self)()

    def observe(self, record: dict, observer_name: str) -> None:
        """Called after every move in the game (including this player's own).

        ``record`` is a ledger-format move dict (see app.ml.archetypes.move_record).
        Stateless players ignore it; adaptive players use it to model opponents.
        """
        return None

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
