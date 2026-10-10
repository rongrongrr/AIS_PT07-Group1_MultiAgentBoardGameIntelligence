"""Local game simulation: bag management and dealing.

The rules engine is deliberately deal-agnostic; this module owns the
stochastic part (drawing tiles from the bag, refilling from the lid) so
that MCTS rollouts, self-play data generation, and tournaments can run
entirely offline, and the live-platform adapter can skip it (the website
deals for us there).
"""

from __future__ import annotations

import random
from typing import Optional

from .state import NUM_COLORS, GameState


def draw_tiles(state: GameState, n: int, rng: random.Random) -> list:
    """Draw up to ``n`` tiles from the bag, refilling from the lid when
    the bag empties. Returns a list of colors (may be shorter than ``n``
    if bag and lid are both exhausted)."""
    drawn = []
    for _ in range(n):
        total = sum(state.bag)
        if total == 0:
            if sum(state.lid) == 0:
                break
            state.bag, state.lid = state.lid, [0] * NUM_COLORS
            total = sum(state.bag)
        pick = rng.randrange(total)
        for color in range(NUM_COLORS):
            if pick < state.bag[color]:
                state.bag[color] -= 1
                drawn.append(color)
                break
            pick -= state.bag[color]
    return drawn


def deal_round(state: GameState, rng: Optional[random.Random] = None) -> None:
    """Fill every factory with 4 tiles from the bag."""
    rng = rng or random.Random()
    for factory in state.factories:
        for color in range(NUM_COLORS):
            factory[color] = 0
        for color in draw_tiles(state, 4, rng):
            factory[color] += 1


def new_game(
    num_players: int = 2,
    seed: Optional[int] = None,
    player_names: Optional[list] = None,
) -> GameState:
    """Create a freshly dealt game."""
    state = GameState(num_players=num_players)
    if player_names:
        for board, name in zip(state.players, player_names):
            board.name = name
    deal_round(state, random.Random(seed))
    return state
