"""Search tactician tests: minimax and MCTS."""

import random

import pytest

from tiles.agents.base import DecisionContext
from tiles.agents.tacticians.mcts import MCTSTactician
from tiles.agents.tacticians.minimax import MinimaxTactician
from tiles.agents.tacticians.random_tactician import RandomTactician
from tiles.core import (
    BLUE,
    RED,
    WHITE,
    GameState,
    deal_round,
    is_legal,
    legal_actions,
    new_game,
    step,
    wall_col_for,
)
from tiles.core.state import wall_bit


def ctx_for(state, **kwargs):
    return DecisionContext(
        state=state,
        player_index=state.current_player,
        legal=legal_actions(state),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Basic contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tactician",
    [MinimaxTactician(depth=2), MCTSTactician(simulations=50)],
    ids=["minimax", "mcts"],
)
def test_returns_legal_action_and_report(tactician):
    state = new_game(2, seed=1)
    decision = tactician.decide(ctx_for(state, rng_seed=1))
    assert is_legal(state, decision.action)
    report = decision.report
    assert report is not None and report.candidates
    assert report.candidates[0].action == decision.action
    assert report.elapsed_ms >= 0


def test_mcts_deterministic_with_seed():
    actions = []
    for _ in range(2):
        state = new_game(2, seed=5)
        decision = MCTSTactician(simulations=80).decide(
            ctx_for(state, rng_seed=123)
        )
        actions.append(decision.action)
    assert actions[0] == actions[1]


# ---------------------------------------------------------------------------
# Tactical correctness: prefer completing a high-scoring line
# ---------------------------------------------------------------------------


def tactical_state() -> GameState:
    """Player 0 can complete pattern row 0 with one blue tile, landing at
    wall (0,0) atop an existing vertical run of 3 — worth 4 points plus
    column progress. The only alternative source is junk red that mostly
    overflows to the floor."""
    state = GameState(num_players=2)
    board = state.players[0]
    for r in (1, 2, 3):
        board.wall |= wall_bit(r, 0)
    # Make red useless for player 0's row 0 neighbours: red already on wall
    # nowhere relevant; red picks simply have no completion value.
    state.factories[0][BLUE] = 1
    state.factories[0][WHITE] = 3
    state.factories[1][RED] = 4
    state.current_player = 0
    return state


def completes_blue_row0(action) -> bool:
    return action.color == BLUE and action.dest_row == 0


def test_minimax_picks_completing_move():
    state = tactical_state()
    decision = MinimaxTactician(depth=2).decide(ctx_for(state))
    assert completes_blue_row0(decision.action), str(decision.action)


def test_mcts_picks_completing_move():
    state = tactical_state()
    decision = MCTSTactician(simulations=200).decide(
        ctx_for(state, rng_seed=7)
    )
    assert completes_blue_row0(decision.action), str(decision.action)


# ---------------------------------------------------------------------------
# Opponent model injection
# ---------------------------------------------------------------------------


def test_mcts_uses_opponent_policy():
    state = new_game(2, seed=3)
    calls = []

    def stub_policy(s, player_index, legal):
        calls.append(player_index)
        # Uniform over legal, keyed by action_id per the contract.
        p = 1.0 / len(legal)
        return {a.action_id: p for a in legal}

    decision = MCTSTactician(
        simulations=60, use_opponent_model=True
    ).decide(ctx_for(state, rng_seed=2, opponent_policy=stub_policy))
    assert calls, "opponent policy was never consulted"
    assert all(p != state.current_player for p in calls)
    assert decision.report.used_opponent_model


def test_mcts_without_model_ignores_policy():
    state = new_game(2, seed=3)
    decision = MCTSTactician(simulations=30).decide(
        ctx_for(state, rng_seed=2, opponent_policy=lambda *a: {})
    )
    assert not decision.report.used_opponent_model


# ---------------------------------------------------------------------------
# Strength smoke test
# ---------------------------------------------------------------------------


def play_game(agents, seed) -> int:
    state = new_game(2, seed=seed)
    rng = random.Random(seed)
    while not state.is_game_over:
        agent = agents[state.current_player]
        decision = agent.decide(ctx_for(state, rng_seed=seed))
        _, round_result = step(state, decision.action)
        if round_result is not None and not round_result.game_over:
            deal_round(state, rng)
    return state.winner()


def test_mcts_beats_random():
    mcts_wins = 0
    for seed in (11, 22, 33):
        winner = play_game(
            [MCTSTactician(simulations=150), RandomTactician(seed)], seed
        )
        mcts_wins += winner == 0
    assert mcts_wins >= 2, f"MCTS won only {mcts_wins}/3 vs random"
