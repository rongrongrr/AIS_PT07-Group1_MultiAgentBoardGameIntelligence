"""Abstract base classes for Machine Players and Profiling Agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from tiles.models.schemas import GameAction, GameStateData, MoveRecord


class MachinePlayer(ABC):
    """Abstract base class for all Machine Players."""

    @abstractmethod
    async def decide(self, game_state: GameStateData, player_index: int) -> GameAction:
        """Given the current game state and player index, return the action to take."""
        ...

    #: True for players that spend noticeable CPU time deciding (tree search). The session runs them in a
    #: worker thread so one bot's thinking cannot freeze the event loop (other bots, the UI WebSocket,
    #: and the move timeout itself).
    cpu_bound: bool = False

    def set_time_limit(self, seconds: float) -> None:
        """Called by the session with its per-move limit; search players shrink their budget to fit."""
        if hasattr(self, "time_budget_s"):
            self.time_budget_s = min(self.time_budget_s, 0.7 * seconds)

    def clone(self) -> MachinePlayer:
        """A fresh instance for one game (per-game state must not be shared between sessions)."""
        return type(self)()

    def observe(self, record: dict, observer_name: str) -> None:
        """Called after every move in the game (including this player's own).

        ``record`` is a ledger-format move dict (see tiles.ml.archetypes.move_record).
        Stateless players ignore it; adaptive players use it to model opponents.
        """
        return

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
