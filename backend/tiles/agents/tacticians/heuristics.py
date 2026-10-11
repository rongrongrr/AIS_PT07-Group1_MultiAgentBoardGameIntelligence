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
from tiles.core.state import FLOOR_CAPACITY, PlayerBoard, wall_bit, wall_col_for, wall_color_at

DEFAULT_WEIGHTS: Dict[str, float] = {
    "immediate_points": 3.0,  # points scored when the line completes
    "line_progress": 1.0,  # partial fill value
    "near_completion": 0.8,  # extra value when a line gets close
    "floor_penalty": 1.2,  # weight on floor penalty points (negative)
    "first_player": 0.7,  # net value of taking the FPT
    "bonus_potential": 0.6,  # progress toward row/col/color bonuses
    "denial": 0.4,  # taking tiles an opponent visibly wants
}


#: Optional components. They are off unless a weight for them is given
#: (``DEFAULT_WEIGHTS`` is unchanged, so the Profiler's population prior and
#: every existing result stay as they were). The values are the nominal
#: strengths used in the heuristic study (docs/FINAL_REPORT.md, section 10.8).
EXPERIMENTAL_WEIGHTS: Dict[str, float] = {
    "round_end_feasibility": 1.0,  # penalise lines that cannot finish this round
    "floor_outlook": 1.0,  # penalise moves that leave too little room for later takes
    "spoil": 1.0,  # leave the next player tiles they cannot place
    "bonus_reach": 1.0,  # value column/colour bonuses that are near and still reachable
}

#: Weights used in the closing rounds (see ``is_endgame``): cash in points and
#: bonuses, stop building for later and stop chasing the first-player token.
ENDGAME_WEIGHTS: Dict[str, float] = {
    "immediate_points": 4.5,
    "bonus_potential": 1.5,
    "line_progress": 0.3,
    "near_completion": 0.3,
    "first_player": 0.2,
    "denial": 0.2,
}


def is_endgame(state: GameState) -> bool:
    """True once any wall has a row one tile from complete: the game ends
    after the round in which a row is completed, so it is close."""
    return any(
        sum(board.wall_has(r, c) for c in range(5)) >= 4
        for board in state.players
        for r in range(5)
    )


def endgame_weights(weights: Dict[str, float], state: GameState) -> Dict[str, float]:
    return {**weights, **ENDGAME_WEIGHTS} if is_endgame(state) else weights

#: First-player-token value by table size, from the follow-up study: going
#: first matters little with two players and clearly more with three or four.
TABLE_FIRST_PLAYER: Dict[int, float] = {2: 0.7, 3: 2.0, 4: 2.0}


def table_weights(weights: Dict[str, float], num_players: int) -> Dict[str, float]:
    """``weights`` with the first-player-token value set for the table size."""
    return {**weights, "first_player": TABLE_FIRST_PLAYER.get(num_players, weights["first_player"])}


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


def _on_table(state: GameState, color: int) -> int:
    return sum(f[color] for f in state.factories) + state.center[color]


def _round_end_feasibility(
    state: GameState,
    action: Action,
    source,
    taken: int,
    to_line: int,
    completes: bool,
) -> float:
    """0 when the line can still be completed this round, down to -1 when
    the tiles it needs are no longer on the table. A line left open does
    not cost points, but it blocks its row for other colours."""
    if action.to_floor or not to_line or completes:
        return 0.0
    board = state.current_board()
    need = (action.dest_row + 1) - (board.pattern_counts[action.dest_row] + to_line)
    supply = _on_table(state, action.color) - taken
    return -max(0, need - supply) / need


def _floor_outlook(
    state: GameState,
    board: PlayerBoard,
    action: Action,
    source,
    taken: int,
    to_line: int,
    floor_now: int,
) -> float:
    """Expected extra floor penalty from tiles the player will probably
    have to take later this round but has no room for after this move.

    The player takes about ``1 / num_players`` of what stays on the table.
    Whatever exceeds the free pattern-line space goes to the floor.
    """
    left = sum(_on_table(state, c) for c in range(len(source))) - taken
    expected = -(-left // state.num_players)  # ceiling
    space = sum(board.pattern_space(r) for r in range(5))
    if not action.to_floor:
        space -= to_line
    excess = max(0, expected - max(space, 0))
    return float(_floor_delta(board, floor_now + excess) - _floor_delta(board, floor_now))


def _spoil(state: GameState, action: Action, taken: int) -> float:
    """Share of the tiles left on the table that the next player has no
    pattern line for (0 to 1). Higher means they are more likely to take
    floor penalties."""
    nxt = state.players[(state.current_player + 1) % state.num_players]
    total = bound = 0
    for color in range(len(state.center)):
        left = _on_table(state, color) - (taken if color == action.color else 0)
        total += left
        if left and not any(nxt.can_place(r, color) for r in range(5)):
            bound += left
    return bound / total if total else 0.0


def _bonus_reach(state: GameState, board: PlayerBoard, action: Action) -> float:
    """Progress toward a column or colour bonus when this move completes a
    line, counted only for lines that are at least three-fifths done and
    scaled by whether the tiles still missing are in the bag or on the table."""
    if action.to_floor:
        return 0.0
    row = action.dest_row
    col = wall_col_for(row, action.color)
    wall = board.wall | wall_bit(row, col)

    def filled(r: int, c: int) -> bool:
        return bool(wall & wall_bit(r, c))

    def supply(color: int) -> int:
        return state.bag[color] + _on_table(state, color)

    value = 0.0
    missing = [r for r in range(5) if not filled(r, col)]
    n = 5 - len(missing)
    if n >= 3:
        feas = sum(min(1.0, supply(wall_color_at(r, col)) / 3) for r in missing) / len(missing) if missing else 1.0
        value += 7.0 * (n / 5) ** 3 * feas
    missing = [r for r in range(5) if not filled(r, wall_col_for(r, action.color))]
    n = 5 - len(missing)
    if n >= 3:
        feas = min(1.0, supply(action.color) / (3 * len(missing))) if missing else 1.0
        value += 10.0 * (n / 5) ** 3 * feas
    return value


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

    if weights.get("round_end_feasibility"):
        components["round_end_feasibility"] = _round_end_feasibility(
            state, action, source, taken, to_line, completes
        )
    if weights.get("floor_outlook"):
        components["floor_outlook"] = _floor_outlook(
            state, board, action, source, taken, to_line, overflow + fpt_extra
        )

    if weights.get("spoil"):
        components["spoil"] = _spoil(state, action, taken)
    if weights.get("bonus_reach") and completes:
        components["bonus_reach"] = _bonus_reach(state, board, action)

    total = sum(weights.get(k, 0.0) * v for k, v in components.items())
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
