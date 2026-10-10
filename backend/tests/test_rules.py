"""Rules engine tests: legality, scoring, transitions, invariants."""

import random

import pytest

from tiles.core import (
    BLACK,
    BLUE,
    CENTER,
    FIRST_PLAYER,
    FLOOR,
    RED,
    WHITE,
    YELLOW,
    Action,
    GameState,
    apply_action,
    check_action,
    deal_round,
    end_game_bonuses,
    legal_action_mask,
    legal_actions,
    new_game,
    placement_score,
    resolve_round,
    step,
    wall_col_for,
)
from tiles.core.state import PlayerBoard, wall_bit


def make_state(**kwargs) -> GameState:
    """A 2-player state with empty factories/center unless overridden."""
    state = GameState(num_players=2)
    for key, value in kwargs.items():
        setattr(state, key, value)
    return state


# ---------------------------------------------------------------------------
# Wall geometry
# ---------------------------------------------------------------------------


def test_wall_pattern_matches_standard_azul():
    # Row 0: blue yellow red black white
    assert [wall_col_for(0, c) for c in (BLUE, YELLOW, RED, BLACK, WHITE)] == [
        0,
        1,
        2,
        3,
        4,
    ]
    # Row 1 shifts right: white sits in column 0
    assert wall_col_for(1, WHITE) == 0
    assert wall_col_for(1, BLUE) == 1
    assert wall_col_for(4, BLUE) == 4


# ---------------------------------------------------------------------------
# Legality
# ---------------------------------------------------------------------------


def test_legal_actions_from_factory_and_center():
    state = make_state()
    state.factories[0][BLUE] = 2
    state.factories[0][RED] = 2
    state.center[YELLOW] = 1
    actions = legal_actions(state)
    # 3 (source,color) pairs x (5 rows + floor) = 18 on an empty board
    assert len(actions) == 18
    assert all(check_action(state, a) is None for a in actions)


def test_cannot_place_color_already_on_wall_row():
    state = make_state()
    state.factories[0][BLUE] = 1
    board = state.players[0]
    board.wall |= wall_bit(2, wall_col_for(2, BLUE))
    violation = check_action(state, Action(0, BLUE, 2))
    assert violation is not None and violation.predicate == "wall_slot_open"


def test_cannot_mix_colors_on_pattern_line():
    state = make_state()
    state.factories[0][RED] = 1
    board = state.players[0]
    board.pattern_colors[3] = BLUE
    board.pattern_counts[3] = 1
    violation = check_action(state, Action(0, RED, 3))
    assert violation is not None and violation.predicate == "line_color_matches"


def test_cannot_take_missing_color():
    state = make_state()
    state.factories[0][BLUE] = 1
    violation = check_action(state, Action(0, RED, FLOOR))
    assert violation is not None and violation.predicate == "source_has_color"


def test_action_mask_matches_legal_actions():
    state = new_game(2, seed=7)
    mask = legal_action_mask(state)
    ids = {a.action_id for a in legal_actions(state)}
    assert sum(mask) == len(ids)
    assert all(mask[i] == 1 for i in ids)
    # round-trips
    for i in ids:
        assert Action.from_action_id(i).action_id == i


# ---------------------------------------------------------------------------
# Applying actions
# ---------------------------------------------------------------------------


def test_factory_pick_moves_rest_to_center():
    state = make_state()
    state.factories[0] = [2, 1, 1, 0, 0]  # 2 blue, 1 yellow, 1 red
    apply_action(state, Action(0, BLUE, 1))
    assert state.factories[0] == [0] * 5
    assert state.center[YELLOW] == 1 and state.center[RED] == 1
    board = state.players[0]
    assert board.pattern_colors[1] == BLUE and board.pattern_counts[1] == 2


def test_overflow_goes_to_floor():
    state = make_state()
    state.factories[0][RED] = 4
    move = apply_action(state, Action(0, RED, 0))  # row 0 holds 1 tile
    assert move.tiles_to_line == 1 and move.tiles_to_floor == 3
    assert state.players[0].floor == [RED] * 3


def test_first_center_pick_takes_token():
    state = make_state()
    state.center[BLUE] = 2
    move = apply_action(state, Action(CENTER, BLUE, 1))
    assert move.took_first_player_token
    assert FIRST_PLAYER in state.players[0].floor
    assert state.next_first_player == 0
    assert not state.center_has_fpt


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_placement_score_isolated_is_one():
    wall = wall_bit(2, 2)
    assert placement_score(wall, 2, 2) == 1


def test_placement_score_counts_both_runs():
    # Horizontal run of 3 through (2,2), vertical run of 2.
    wall = (
        wall_bit(2, 1)
        | wall_bit(2, 2)
        | wall_bit(2, 3)
        | wall_bit(1, 2)
    )
    assert placement_score(wall, 2, 2) == 3 + 2


def test_end_game_bonuses():
    board = PlayerBoard()
    for c in range(5):
        board.wall |= wall_bit(0, c)  # one full row
    for r in range(5):
        board.wall |= wall_bit(r, wall_col_for(r, BLUE))  # all blues
    bonuses = end_game_bonuses(board)
    assert bonuses["rows"] == 1 and bonuses["colors"] == 1
    assert bonuses["points"] == 2 + 10 + 7 * bonuses["cols"]


# ---------------------------------------------------------------------------
# Round resolution
# ---------------------------------------------------------------------------


def test_resolve_round_tiles_walls_and_penalizes_floor():
    state = make_state()
    board = state.players[0]
    board.pattern_colors[1] = BLUE
    board.pattern_counts[1] = 2  # full
    board.floor = [RED, FIRST_PLAYER]
    state.next_first_player = 0
    result = resolve_round(state)
    assert board.wall_has_color(1, BLUE)
    assert board.pattern_counts[1] == 0 and board.pattern_colors[1] == -1
    # 1 point placement, -2 floor (two floor slots), clamped at 0
    assert board.score == 0
    assert result.floor_penalties[0] == -2
    assert state.lid[BLUE] == 1  # row-1 line: 1 surplus tile to lid
    assert state.lid[RED] == 1
    assert state.round_number == 2
    assert state.current_player == 0
    assert state.center_has_fpt


def test_score_never_negative():
    state = make_state()
    board = state.players[0]
    board.floor = [RED] * 7
    resolve_round(state)
    assert board.score == 0


def test_game_ends_on_completed_row():
    state = make_state()
    board = state.players[0]
    for c in range(4):
        board.wall |= wall_bit(0, c)
    # Completing pattern line for the missing color of row 0, col 4 = white
    board.pattern_colors[0] = WHITE
    board.pattern_counts[0] = 1
    result = resolve_round(state)
    assert result.game_over
    assert state.is_game_over
    assert result.bonuses is not None
    assert state.winner() == 0


# ---------------------------------------------------------------------------
# Full-game invariants
# ---------------------------------------------------------------------------


def total_tiles(state: GameState) -> int:
    n = sum(state.bag) + sum(state.lid) + sum(state.center)
    n += sum(sum(f) for f in state.factories)
    for board in state.players:
        n += sum(board.pattern_counts)
        n += sum(1 for t in board.floor if t != FIRST_PLAYER)
        n += bin(board.wall).count("1")
    return n


@pytest.mark.parametrize("num_players", [2, 3, 4])
@pytest.mark.parametrize("seed", [1, 42])
def test_random_game_terminates_and_conserves_tiles(num_players, seed):
    rng = random.Random(seed)
    state = new_game(num_players, seed=seed)
    assert total_tiles(state) == 100
    turns = 0
    while not state.is_game_over:
        actions = legal_actions(state)
        assert actions, "drafting phase must always offer a legal action"
        _, round_result = step(state, rng.choice(actions))
        assert total_tiles(state) == 100
        if round_result is not None and not round_result.game_over:
            deal_round(state, rng)
            assert total_tiles(state) == 100
        turns += 1
        assert turns < 1000, "game did not terminate"
    assert state.round_number <= 12
    assert any(p.completed_rows() > 0 for p in state.players)
