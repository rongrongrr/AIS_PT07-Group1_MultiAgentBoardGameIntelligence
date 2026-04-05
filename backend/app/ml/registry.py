"""Registry for Machine Players and Profiling Agents."""

from __future__ import annotations

from typing import Dict, Optional

from app.ml.base import MachinePlayer, ProfilerAgent
from app.ml.greedy_player import GreedyPlayer
from app.ml.random_player import RandomPlayer


class ModelRegistry:
    """Central registry for all ML models (players and profilers)."""

    def __init__(self):
        self._players: Dict[str, MachinePlayer] = {}
        self._profilers: Dict[str, ProfilerAgent] = {}
        self._register_defaults()

    def _register_defaults(self):
        self.register_player(RandomPlayer())
        self.register_player(GreedyPlayer())

    def register_player(self, player: MachinePlayer):
        self._players[player.name] = player

    def register_profiler(self, profiler: ProfilerAgent):
        self._profilers[profiler.name] = profiler

    def get_player(self, name: str) -> Optional[MachinePlayer]:
        return self._players.get(name)

    def get_profiler(self, name: str) -> Optional[ProfilerAgent]:
        return self._profilers.get(name)

    def list_players(self) -> list:
        return [{"name": p.name, "type": "player"} for p in self._players.values()]

    def list_profilers(self) -> list:
        return [{"name": p.name, "type": "profiler"} for p in self._profilers.values()]


# Singleton
registry = ModelRegistry()
