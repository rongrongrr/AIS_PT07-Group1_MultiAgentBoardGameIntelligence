"""Registry for Machine Players and Profiling Agents."""

from __future__ import annotations

from typing import Dict, Optional

from tiles.ml.base import MachinePlayer, ProfilerAgent
from tiles.ml.adaptive_player import AdaptivePlayer, AdaptiveRolloutPlayer
from tiles.ml.mcts_player import ConditionedMCTSPlayer, MCTSPlayer
from tiles.ml.td_player import TDPlayer
from tiles.ml.minimax_player import ConditionedMinimaxPlayer, MinimaxPlayer
from tiles.ml.rollout_player import RolloutPlayer
from tiles.ml.greedy_player import (
    BlockerPlayer,
    ColorCollectorPlayer,
    GreedyPlayer,
    RecklessPlayer,
    RusherPlayer,
)
from tiles.ml.random_player import RandomPlayer
from tiles.bridge import CORE_PLAYERS


class ModelRegistry:
    """Central registry for all ML models (players and profilers)."""

    def __init__(self):
        self._players: Dict[str, MachinePlayer] = {}
        self._profilers: Dict[str, ProfilerAgent] = {}
        self._register_defaults()

    def _register_defaults(self):
        self.register_player(RandomPlayer())
        for cls in (GreedyPlayer, ColorCollectorPlayer, RusherPlayer, RecklessPlayer, BlockerPlayer, AdaptivePlayer, RolloutPlayer, AdaptiveRolloutPlayer, MinimaxPlayer,
                    MCTSPlayer, ConditionedMCTSPlayer, ConditionedMinimaxPlayer, TDPlayer, *CORE_PLAYERS):
            self.register_player(cls())

    def register_player(self, player: MachinePlayer):
        self._players[player.name] = player

    def register_profiler(self, profiler: ProfilerAgent):
        self._profilers[profiler.name] = profiler

    def get_player(self, name: str) -> Optional[MachinePlayer]:
        return self._players.get(name)

    def create_player(self, name: str) -> Optional[MachinePlayer]:
        """A fresh instance of a registered player (so per-game state is not shared)."""
        proto = self._players.get(name)
        return proto.clone() if proto is not None else None

    def unregister_player(self, name: str) -> None:
        self._players.pop(name, None)

    def get_profiler(self, name: str) -> Optional[ProfilerAgent]:
        return self._profilers.get(name)

    def list_players(self) -> list:
        return [{"name": p.name, "type": "player"} for p in self._players.values()]

    def list_profilers(self) -> list:
        return [{"name": p.name, "type": "profiler"} for p in self._profilers.values()]


# Singleton
registry = ModelRegistry()
