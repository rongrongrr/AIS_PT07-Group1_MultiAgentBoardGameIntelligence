"""Optional heuristic components and the table-aware first-player weight."""

import pytest

from tiles.agents.base import DecisionContext
from tiles.agents.tacticians import make_tactician
from tiles.agents.tacticians.heuristics import (
    DEFAULT_WEIGHTS,
    TABLE_FIRST_PLAYER,
    rank_actions,
    score_action,
    table_weights,
)
from tiles.core import legal_actions, new_game
from tiles.core.state import wall_col_for


def _state(n=2, seed=4):
    return new_game(n, seed=seed)


def test_defaults_are_unchanged_and_new_components_are_off():
    state = _state()
    action = legal_actions(state)[0]
    _, comps = score_action(state, action)
    assert "floor_outlook" not in comps and "round_end_feasibility" not in comps
    assert set(DEFAULT_WEIGHTS) == {
        "immediate_points", "line_progress", "near_completion", "floor_penalty",
        "first_player", "bonus_potential", "denial",
    }


def test_components_appear_only_when_weighted_and_are_never_positive():
    for n in (2, 3, 4):
        state = _state(n, seed=n)
        weights = {**DEFAULT_WEIGHTS, "floor_outlook": 1.0, "round_end_feasibility": 1.0}
        for action in legal_actions(state):
            _, comps = score_action(state, action, weights)
            assert -1.0 <= comps["round_end_feasibility"] <= 0.0
            assert comps["floor_outlook"] <= 0.0


def test_round_end_feasibility_flags_a_line_that_cannot_finish():
    state = _state()
    # Row 5 needs five tiles; make a single tile of colour 0 available.
    state.factories = [[0] * 5 for _ in state.factories]
    state.center = [0] * 5
    state.factories[0][0] = 1
    state.center_has_fpt = False
    weights = {**DEFAULT_WEIGHTS, "round_end_feasibility": 1.0}
    row5 = [a for a in legal_actions(state) if not a.to_floor and a.dest_row == 4][0]
    _, comps = score_action(state, row5, weights)
    assert comps["round_end_feasibility"] == pytest.approx(-1.0)  # needs 4 more tiles, none left
    row1 = [a for a in legal_actions(state) if not a.to_floor and a.dest_row == 0][0]
    assert score_action(state, row1, weights)[1]["round_end_feasibility"] == 0.0  # completes


def test_floor_outlook_penalises_a_crowded_board():
    state = _state()
    board = state.current_board()
    for row in range(5):
        board.pattern_counts[row] = row  # almost no room left on the board
        board.pattern_colors[row] = row
    weights = {**DEFAULT_WEIGHTS, "floor_outlook": 1.0}
    values = [score_action(state, a, weights)[1]["floor_outlook"] for a in legal_actions(state)]
    assert min(values) < 0.0


def test_table_weights_and_greedy_flag():
    assert table_weights(DEFAULT_WEIGHTS, 2)["first_player"] == TABLE_FIRST_PLAYER[2]
    assert table_weights(DEFAULT_WEIGHTS, 4)["first_player"] == TABLE_FIRST_PLAYER[4]
    assert table_weights(DEFAULT_WEIGHTS, 5)["first_player"] == DEFAULT_WEIGHTS["first_player"]
    state = _state(4)
    ctx = DecisionContext(state, 0, legal_actions(state))
    aware = make_tactician("greedy", table_aware=True).decide(ctx)
    plain = make_tactician("greedy").decide(ctx)
    assert aware.report.notes["weights"]["first_player"] == 2.0
    assert plain.report.notes["weights"]["first_player"] == DEFAULT_WEIGHTS["first_player"]


def test_rank_actions_still_sorted_with_new_components():
    state = _state(3)
    weights = {**DEFAULT_WEIGHTS, "floor_outlook": 2.0, "round_end_feasibility": 2.0}
    scores = [s for _, s, _ in rank_actions(state, legal_actions(state), weights)]
    assert scores == sorted(scores, reverse=True)


def test_spoil_and_bonus_reach_are_bounded_and_only_present_when_weighted():
    for n in (2, 3, 4):
        state = _state(n, seed=10 + n)
        weights = {**DEFAULT_WEIGHTS, "spoil": 1.0, "bonus_reach": 1.0}
        for action in legal_actions(state):
            _, comps = score_action(state, action, weights)
            assert 0.0 <= comps["spoil"] <= 1.0
            assert comps.get("bonus_reach", 0.0) >= 0.0
            assert "spoil" not in score_action(state, action)[1]


def test_spoil_is_high_when_the_next_player_cannot_place_what_is_left():
    state = _state()
    nxt = state.players[1]
    for row in range(5):  # every line full: nothing can be placed
        nxt.pattern_counts[row] = row + 1
        nxt.pattern_colors[row] = 0
    weights = {**DEFAULT_WEIGHTS, "spoil": 1.0}
    action = legal_actions(state)[0]
    assert score_action(state, action, weights)[1]["spoil"] == pytest.approx(1.0)


def test_bonus_reach_rewards_a_nearly_complete_column():
    state = _state()
    board = state.current_board()
    from tiles.core.state import wall_bit

    for r in range(4):  # column 0 filled except the last row
        board.wall |= wall_bit(r, 0)
    state.bag = [10] * 5
    colour = [c for c in range(5) if wall_col_for(4, c) == 0][0]
    state.factories = [[0] * 5 for _ in state.factories]
    state.center = [0] * 5
    state.factories[0][colour] = 5
    action = [a for a in legal_actions(state) if not a.to_floor and a.dest_row == 4][0]
    _, comps = score_action(state, action, {**DEFAULT_WEIGHTS, "bonus_reach": 1.0})
    assert comps["bonus_reach"] > 0


def test_endgame_detection_and_weights():
    from tiles.agents.tacticians.heuristics import ENDGAME_WEIGHTS, endgame_weights, is_endgame
    from tiles.core.state import wall_bit

    state = _state()
    assert not is_endgame(state)
    assert endgame_weights(DEFAULT_WEIGHTS, state) == DEFAULT_WEIGHTS
    for c in range(4):
        state.players[1].wall |= wall_bit(2, c)
    assert is_endgame(state)
    assert endgame_weights(DEFAULT_WEIGHTS, state)["immediate_points"] == ENDGAME_WEIGHTS["immediate_points"]
    ctx = DecisionContext(state, 0, legal_actions(state))
    aware = make_tactician("greedy", endgame_aware=True).decide(ctx)
    assert aware.report.notes["weights"]["immediate_points"] == ENDGAME_WEIGHTS["immediate_points"]
