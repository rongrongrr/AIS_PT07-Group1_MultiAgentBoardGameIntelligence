"""Deterministic Azul rules engine.

This module is the single authority on rule legality and state
transitions. It is pure: no I/O, no randomness (dealing lives in
``simulator``), and it never talks to an LLM. The Validator agent wraps
these functions to gate every proposed move.

All mutating functions operate in place on a ``GameState``; callers who
need to preserve the original (e.g. MCTS) clone first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .actions import CENTER, FLOOR, Action
from .state import (
    FIRST_PLAYER,
    FLOOR_CAPACITY,
    NUM_COLORS,
    PHASE_DRAFTING,
    PHASE_GAME_OVER,
    GameState,
    PlayerBoard,
    wall_bit,
    wall_col_for,
)

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass
class RuleViolation:
    """Machine-readable predicate failure, consumed by the Validator."""

    predicate: str
    message: str


def check_action(state: GameState, action: Action) -> Optional[RuleViolation]:
    """Return None if legal, otherwise the first violated predicate."""
    if state.phase != PHASE_DRAFTING:
        return RuleViolation("phase_is_drafting", "the game is over")
    if not (0 <= action.color < NUM_COLORS):
        return RuleViolation("color_exists", f"unknown color {action.color}")

    if action.from_center:
        source = state.center
        where = "the center pool"
    else:
        if not (0 <= action.source_index < len(state.factories)):
            return RuleViolation(
                "source_exists",
                f"factory {action.source_index} does not exist",
            )
        source = state.factories[action.source_index]
        where = f"factory {action.source_index}"
    if source[action.color] == 0:
        return RuleViolation(
            "source_has_color",
            f"no {action.color} tiles in {where}",
        )

    if not action.to_floor:
        if not (0 <= action.dest_row < 5):
            return RuleViolation(
                "dest_exists", f"pattern row {action.dest_row} does not exist"
            )
        board = state.current_board()
        if board.wall_has_color(action.dest_row, action.color):
            return RuleViolation(
                "wall_slot_open",
                f"color already on wall row {action.dest_row}",
            )
        line_color = board.pattern_colors[action.dest_row]
        if line_color != -1 and line_color != action.color:
            return RuleViolation(
                "line_color_matches",
                f"pattern row {action.dest_row} holds a different color",
            )
        if board.pattern_counts[action.dest_row] >= action.dest_row + 1:
            return RuleViolation(
                "line_has_space", f"pattern row {action.dest_row} is full"
            )
    return None


def is_legal(state: GameState, action: Action) -> bool:
    return check_action(state, action) is None


def legal_actions(state: GameState) -> List[Action]:
    """All legal actions for the current player."""
    if state.phase != PHASE_DRAFTING:
        return []
    board = state.current_board()
    actions: List[Action] = []

    sources: List[tuple] = [
        (i, f) for i, f in enumerate(state.factories) if any(f)
    ]
    if any(state.center):
        sources.append((CENTER, state.center))

    for source_index, counts in sources:
        for color in range(NUM_COLORS):
            if counts[color] == 0:
                continue
            for row in range(5):
                if board.can_place(row, color):
                    actions.append(Action(source_index, color, row))
            actions.append(Action(source_index, color, FLOOR))
    return actions


def legal_action_mask(state: GameState) -> List[int]:
    """300-slot binary mask aligned with ``Action.action_id``."""
    from .actions import MAX_ACTIONS

    mask = [0] * MAX_ACTIONS
    for action in legal_actions(state):
        mask[action.action_id] = 1
    return mask


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def placement_score(wall: int, row: int, col: int) -> int:
    """Score for placing a tile at (row, col) given the wall *after*
    placement. Contiguous horizontal + vertical runs; isolated tile = 1."""

    def filled(r: int, c: int) -> bool:
        return bool(wall & wall_bit(r, c))

    h = 1
    c = col - 1
    while c >= 0 and filled(row, c):
        h += 1
        c -= 1
    c = col + 1
    while c < 5 and filled(row, c):
        h += 1
        c += 1

    v = 1
    r = row - 1
    while r >= 0 and filled(r, col):
        v += 1
        r -= 1
    r = row + 1
    while r < 5 and filled(r, col):
        v += 1
        r += 1

    if h == 1 and v == 1:
        return 1
    return (h if h > 1 else 0) + (v if v > 1 else 0)


def end_game_bonuses(board: PlayerBoard) -> dict:
    rows = sum(
        1 for r in range(5) if all(board.wall_has(r, c) for c in range(5))
    )
    cols = sum(
        1 for c in range(5) if all(board.wall_has(r, c) for r in range(5))
    )
    colors = sum(
        1
        for color in range(NUM_COLORS)
        if all(board.wall_has_color(r, color) for r in range(5))
    )
    return {
        "rows": rows,
        "cols": cols,
        "colors": colors,
        "points": rows * 2 + cols * 7 + colors * 10,
    }


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


@dataclass
class MoveResult:
    """What happened when an action was applied (pre-round-resolution)."""

    action: Action
    player_index: int
    tiles_taken: int
    tiles_to_line: int
    tiles_to_floor: int
    took_first_player_token: bool
    completed_line: bool  # pattern line became full


@dataclass
class TilingEvent:
    """One tile moved from a full pattern line to the wall."""

    player_index: int
    row: int
    col: int
    color: int
    points: int


@dataclass
class RoundResult:
    """Outcome of the wall-tiling phase at the end of a round."""

    round_number: int
    tilings: List[TilingEvent] = field(default_factory=list)
    floor_penalties: List[int] = field(default_factory=list)  # per player
    scores: List[int] = field(default_factory=list)  # after this round
    game_over: bool = False
    bonuses: Optional[List[dict]] = None  # per player, only if game_over


def apply_action(state: GameState, action: Action) -> MoveResult:
    """Apply a legal drafting action for the current player, in place.

    Raises ``ValueError`` on an illegal action (call ``check_action``
    first for a structured error). Does NOT resolve the round or advance
    ``current_player`` — use ``step`` for the full turn transition.
    """
    violation = check_action(state, action)
    if violation is not None:
        raise ValueError(f"illegal action {action}: {violation.message}")

    board = state.current_board()
    took_fpt = False

    if action.from_center:
        taken = state.center[action.color]
        state.center[action.color] = 0
        if state.center_has_fpt:
            state.center_has_fpt = False
            board.floor.append(FIRST_PLAYER)
            state.next_first_player = state.current_player
            took_fpt = True
    else:
        factory = state.factories[action.source_index]
        taken = factory[action.color]
        factory[action.color] = 0
        # Remaining tiles go to the center.
        for color in range(NUM_COLORS):
            state.center[color] += factory[color]
            factory[color] = 0

    to_line = 0
    completed = False
    if not action.to_floor:
        space = board.pattern_space(action.dest_row)
        to_line = min(space, taken)
        board.pattern_colors[action.dest_row] = action.color
        board.pattern_counts[action.dest_row] += to_line
        completed = board.pattern_counts[action.dest_row] == action.dest_row + 1
    to_floor = taken - to_line
    for _ in range(to_floor):
        board.floor.append(action.color)

    return MoveResult(
        action=action,
        player_index=state.current_player,
        tiles_taken=taken,
        tiles_to_line=to_line,
        tiles_to_floor=to_floor,
        took_first_player_token=took_fpt,
        completed_line=completed,
    )


def resolve_round(state: GameState) -> RoundResult:
    """Run the wall-tiling phase: move full pattern lines to walls, score
    placements, apply floor penalties, detect game end, apply bonuses.

    Does not redeal (the simulator or live adapter owns dealing).
    """
    result = RoundResult(round_number=state.round_number)

    for idx, board in enumerate(state.players):
        for row in range(5):
            if board.pattern_counts[row] == row + 1:
                color = board.pattern_colors[row]
                col = wall_col_for(row, color)
                board.wall |= wall_bit(row, col)
                points = placement_score(board.wall, row, col)
                board.score += points
                result.tilings.append(
                    TilingEvent(idx, row, col, color, points)
                )
                # One tile to the wall, the rest (row) to the lid.
                state.lid[color] += row
                board.pattern_colors[row] = -1
                board.pattern_counts[row] = 0

        penalty = board.floor_penalty()
        board.score = max(0, board.score + penalty)
        result.floor_penalties.append(penalty)
        for tile in board.floor:
            if tile != FIRST_PLAYER:
                state.lid[tile] += 1
        board.floor.clear()

    result.game_over = any(p.completed_rows() > 0 for p in state.players)
    if result.game_over:
        result.bonuses = []
        for board in state.players:
            bonus = end_game_bonuses(board)
            board.score += bonus["points"]
            result.bonuses.append(bonus)
        state.phase = PHASE_GAME_OVER
    else:
        state.round_number += 1
        state.current_player = (
            state.next_first_player
            if state.next_first_player is not None
            else 0
        )
        state.next_first_player = None
        state.center_has_fpt = True

    result.scores = state.scores()
    return result


def step(state: GameState, action: Action) -> tuple:
    """Full turn transition: apply the action, advance the turn, and
    resolve the round if drafting is exhausted.

    Returns ``(MoveResult, Optional[RoundResult])``. When a round ends
    and the game continues, the caller must redeal (``simulator.deal_round``
    for local games).
    """
    move = apply_action(state, action)
    round_result = None
    if state.drafting_exhausted():
        round_result = resolve_round(state)
    else:
        state.current_player = (state.current_player + 1) % state.num_players
    return move, round_result
