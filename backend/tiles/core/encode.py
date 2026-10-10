"""Numeric encodings of the game state for ML consumers.

Provides a flat float-vector observation (for policy/value networks and
the PettingZoo wrapper) plus the 300-slot action mask re-exported from
the rules engine. Pure Python lists — callers can wrap in numpy.
"""

from __future__ import annotations

from typing import List

from .rules import legal_action_mask
from .state import NUM_COLORS, GameState

MAX_FACTORIES = 9


def encode_player(state: GameState, viewer: int, player: int) -> List[float]:
    board = state.players[player]
    vec: List[float] = []
    # Wall: 25 binary
    vec.extend(
        1.0 if board.wall_has(r, c) else 0.0
        for r in range(5)
        for c in range(5)
    )
    # Pattern lines: per row, color one-hot (5) + fill fraction (1)
    for r in range(5):
        onehot = [0.0] * NUM_COLORS
        if board.pattern_colors[r] != -1:
            onehot[board.pattern_colors[r]] = 1.0
        vec.extend(onehot)
        vec.append(board.pattern_counts[r] / (r + 1))
    # Floor line occupancy + first-player token + normalised score
    vec.append(min(len(board.floor), 7) / 7.0)
    vec.append(1.0 if board.has_first_player_token() else 0.0)
    vec.append(board.score / 100.0)
    return vec


def encode_state(state: GameState, viewer: int) -> List[float]:
    """Observation from ``viewer``'s perspective: own board first, then
    opponents in turn order, then the shared supply."""
    vec: List[float] = []
    order = [
        (viewer + i) % state.num_players for i in range(state.num_players)
    ]
    for player in order:
        vec.extend(encode_player(state, viewer, player))
    # Pad missing players (fixed-size obs for 2-4 player games)
    per_player = 25 + 5 * 6 + 3
    for _ in range(4 - state.num_players):
        vec.extend([0.0] * per_player)

    # Factories: counts / 4
    for i in range(MAX_FACTORIES):
        if i < len(state.factories):
            vec.extend(n / 4.0 for n in state.factories[i])
        else:
            vec.extend([0.0] * NUM_COLORS)
    # Center: counts / 20 + first-player token
    vec.extend(n / 20.0 for n in state.center)
    vec.append(1.0 if state.center_has_fpt else 0.0)
    # Bag and lid: counts / 20
    vec.extend(n / 20.0 for n in state.bag)
    vec.extend(n / 20.0 for n in state.lid)
    # Round number and whether it's the viewer's turn
    vec.append(state.round_number / 10.0)
    vec.append(1.0 if state.current_player == viewer else 0.0)
    return vec


OBS_SIZE = len(encode_state(GameState(num_players=2), 0))

__all__ = ["encode_state", "encode_player", "legal_action_mask", "OBS_SIZE"]
