"""Shared heuristic evaluation.

``score_action`` rates a single drafting action with a decomposition
into named components — the decomposition doubles as XAI evidence.
``evaluate_state`` rates a whole position for one player — used as the
leaf evaluation for Minimax and as the MCTS rollout value.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from tiles.core import (
    FLOOR_PENALTIES,
    Action,
    GameState,
    end_game_bonuses,
    placement_score,
)
from tiles.core.state import FLOOR_CAPACITY, PlayerBoard, wall_bit, wall_col_for

DEFAULT_WEIGHTS: Dict[str, float] = {
    "immediate_points": 3.0,  # points scored when the line completes
    "line_progress": 1.0,  # partial fill value
    "near_completion": 0.8,  # extra value when a line gets close
    "floor_penalty": 1.2,  # weight on floor penalty points (negative)
    "first_player": 0.7,  # net value of taking the FPT
    "bonus_potential": 0.6,  # progress toward row/col/color bonuses
    "denial": 0.4,  # taking tiles an opponent visibly wants
}


def _floor_delta(board: PlayerBoard, extra: int) -> int:
    """Penalty points added by putting ``extra`` more tiles on the floor."""
    start = min(len(board.floor), FLOOR_CAPACITY)
    end = min(start + extra, FLOOR_CAPACITY)
    return sum(FLOOR_PENALTIES[start:end])


def _bonus_progress(board: PlayerBoard, row: int, col: int, color: int) -> float:
    """Marginal progress toward end-game bonuses if a tile lands at
    (row, col). Scaled so a completing tile is worth the full bonus."""
    wall_after = board.wall | wall_bit(row, col)

    def filled(r: int, c: int) -> bool:
        return bool(wall_after & wall_bit(r, c))

    row_n = sum(1 for c in range(5) if filled(row, c))
    col_n = sum(1 for r in range(5) if filled(r, col))
    color_n = sum(
        1 for r in range(5) if filled(r, wall_col_for(r, color))
    )
    value = 0.0
    value += 2.0 * (row_n / 5) ** 2
    value += 7.0 * (col_n / 5) ** 2
    value += 10.0 * (color_n / 5) ** 2
    return value


def _opponent_wants(state: GameState, color: int, player_index: int) -> float:
    """How much visible demand opponents have for ``color`` (0..1)."""
    demand = 0.0
    for i, board in enumerate(state.players):
        if i == player_index:
            continue
        for row in range(5):
            if board.pattern_colors[row] == color and board.pattern_space(row) > 0:
                demand = max(
                    demand, board.pattern_counts[row] / (row + 1)
                )
    return demand


def score_action(
    state: GameState,
    action: Action,
    weights: Dict[str, float] = DEFAULT_WEIGHTS,
) -> Tuple[float, Dict[str, float]]:
    """Heuristic score of ``action`` for the current player, with a
    per-component breakdown (pre-weight values are in the breakdown)."""
    board = state.current_board()
    source = (
        state.center if action.from_center else state.factories[action.source_index]
    )
    taken = source[action.color]

    components: Dict[str, float] = {}

    if action.to_floor:
        to_line, overflow, completes = 0, taken, False
    else:
        space = board.pattern_space(action.dest_row)
        to_line = min(space, taken)
        overflow = taken - to_line
        completes = board.pattern_counts[action.dest_row] + to_line == action.dest_row + 1

    immediate = 0.0
    bonus = 0.0
    if completes:
        col = wall_col_for(action.dest_row, action.color)
        immediate = placement_score(
            board.wall | wall_bit(action.dest_row, col), action.dest_row, col
        )
        bonus = _bonus_progress(board, action.dest_row, col, action.color)
    components["immediate_points"] = immediate
    components["bonus_potential"] = bonus

    progress = 0.0
    near = 0.0
    if not action.to_floor and to_line:
        row_size = action.dest_row + 1
        progress = to_line / row_size
        fill_after = (board.pattern_counts[action.dest_row] + to_line) / row_size
        if not completes and fill_after >= 0.5:
            near = fill_after
    components["line_progress"] = progress
    components["near_completion"] = near

    fpt_extra = 1 if (action.from_center and state.center_has_fpt) else 0
    floor_points = _floor_delta(board, overflow + fpt_extra)
    components["floor_penalty"] = float(floor_points)  # negative or 0

    fpt_value = 0.0
    if fpt_extra:
        # Going first next round is worth roughly one good pick.
        fpt_value = 1.0
    components["first_player"] = fpt_value

    components["denial"] = taken * _opponent_wants(
        state, action.color, state.current_player
    )

    total = sum(weights[k] * v for k, v in components.items())
    return total, components


def evaluate_state(state: GameState, player_index: int) -> float:
    """Static evaluation of a position for ``player_index``, relative to
    the strongest opponent (positive = ahead)."""

    def player_value(i: int) -> float:
        board = state.players[i]
        value = float(board.score)
        # Potential locked in pattern lines.
        for row in range(5):
            if board.pattern_counts[row]:
                fill = board.pattern_counts[row] / (row + 1)
                if board.pattern_counts[row] == row + 1:
                    col = wall_col_for(row, board.pattern_colors[row])
                    value += placement_score(
                        board.wall | wall_bit(row, col), row, col
                    )
                else:
                    value += 1.5 * fill
        value += board.floor_penalty()  # negative
        bonuses = end_game_bonuses(board)
        value += 0.3 * bonuses["points"]
        return value

    mine = player_value(player_index)
    best_opponent = max(
        (
            player_value(i)
            for i in range(state.num_players)
            if i != player_index
        ),
        default=0.0,
    )
    return mine - best_opponent


def rank_actions(
    state: GameState,
    legal: List[Action],
    weights: Dict[str, float] = DEFAULT_WEIGHTS,
) -> List[Tuple[Action, float, Dict[str, float]]]:
    """All legal actions scored and sorted best-first."""
    scored = [
        (action, *score_action(state, action, weights)) for action in legal
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored
