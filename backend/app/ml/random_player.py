"""Reference implementation: a Machine Player that picks a random valid move."""

from __future__ import annotations

import random

from app.azul.rules import get_legal_actions
from app.ml.base import MachinePlayer
from app.models.schemas import GameAction, GameStateData


class RandomPlayer(MachinePlayer):
    """Picks a uniformly random legal action each turn."""

    @property
    def name(self) -> str:
        return "RandomPlayer"

    async def decide(self, game_state: GameStateData, player_index: int) -> GameAction:
        actions = get_legal_actions(game_state, player_index)
        if not actions:
            raise ValueError("No legal actions available")
        return random.choice(actions)
