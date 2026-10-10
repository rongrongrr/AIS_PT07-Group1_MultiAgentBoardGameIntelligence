"""Inferring the moves of players TILES does not control, from board changes."""

import random

from tiles.azul.game import apply_action, new_game, round_over, step_round_boundary
from tiles.azul.rules import get_legal_actions
from tiles.engine.human_tracker import HumanMoveTracker, infer_action


def test_infer_action_recovers_every_legal_move():
    """For any position, every legal move is recovered from the board it produces."""
    rng = random.Random(4)
    sim = new_game(["A", "B", "C"], seed=4)
    checked = 0
    for _ in range(40):
        idx = sim.current
        before = sim.state.model_copy(deep=True)
        for a in get_legal_actions(before, idx)[:12]:
            probe = sim.copy()
            apply_action(probe, a)
            got = infer_action(before, probe.state, idx)
            # moves with an identical resulting board are indistinguishable; the result must reproduce it
            check = sim.copy()
            apply_action(check, got)
            assert check.state.factories == probe.state.factories
            assert [p.pattern_lines for p in check.state.players] == [p.pattern_lines for p in probe.state.players]
            checked += 1
        apply_action(sim, rng.choice(get_legal_actions(sim.state, idx)))
        if round_over(sim.state):
            step_round_boundary(sim)
    assert checked > 200


def test_infer_action_returns_none_for_unrelated_boards():
    sim = new_game(["A", "B"], seed=1)
    before = sim.state.model_copy(deep=True)
    other = new_game(["A", "B"], seed=2).state
    assert infer_action(before, other, 0) is None


def test_tracker_records_only_unknown_players_and_skips_round_ends():
    rng = random.Random(9)
    sim = new_game(["Bot", "Human"], seed=9)
    tracker = HumanMoveTracker(["Bot"])
    recorded = []
    for _ in range(60):
        if sim.finished:
            break
        recorded += tracker.update(sim.state)
        idx = sim.current
        a = rng.choice(get_legal_actions(sim.state, idx))
        apply_action(sim, a)
        if round_over(sim.state):
            recorded += tracker.update(sim.state)          # last move of the round: board still untiled
            step_round_boundary(sim)
        if sim.state.game_over:
            break
    assert recorded and all(m.player_name == "Human" for m in recorded)
    assert len({m.before.round for m in recorded}) >= 2
    assert tracker.unrecorded == 0
    assert tracker.update(None) == []


def test_tracker_counts_unrecoverable_moves():
    sim = new_game(["Bot", "Human"], seed=3)
    tracker = HumanMoveTracker(["Bot"])
    apply_action(sim, get_legal_actions(sim.state, 0)[0])        # bot moves; now it is the human's turn
    tracker.update(sim.state)
    jumped = new_game(["Bot", "Human"], seed=77).state            # board changed in a way no single move explains
    jumped.current_turn = "Bot"
    assert tracker.update(jumped) == []
    assert tracker.unrecorded == 1


def test_infer_action_for_the_last_move_of_a_round():
    """When the platform already shows the tiled, scored board, the move is matched by scoring the round."""
    rng = random.Random(5)
    sim = new_game(["Bot", "Human"], seed=5)
    found = 0
    for _ in range(200):
        if sim.finished:
            break
        idx = sim.current
        before = sim.state.model_copy(deep=True)
        a = rng.choice(get_legal_actions(sim.state, idx))
        apply_action(sim, a)
        if round_over(sim.state):
            step_round_boundary(sim)
            got = infer_action(before, sim.state, idx)       # after = tiled board (next round already dealt)
            assert got is not None
            found += 1
    assert found >= 2
