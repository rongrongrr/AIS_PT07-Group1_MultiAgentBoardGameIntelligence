"""Regression tests for issues found in code review: seeding, the
Validator retry loop, winners and ties, state round-trips, the server's
import side effect, WebSocket subscription, and session config checks."""

import os
import subprocess
import sys

import pytest

from tiles.agents.base import Decision, Tactician
from tiles.agents.validator import Validator
from tiles.core import Action, GameState, legal_actions, new_game, step
from tiles.ledger.store import Ledger
from tiles.orchestration import TurnPipeline
from tiles.server.schemas import SessionCreate
from tiles.server.sessions import (
    MAX_FINISHED_IN_MEMORY,
    SessionError,
    SessionManager,
    validate_session_config,
)
from tiles.sim.match import MatchConfig, MatchRunner


def _local(players, **extra):
    return SessionCreate(mode="local", players=players, **extra)


# -- seeding ------------------------------------------------------------------


def test_seeded_mcts_games_are_reproducible():
    def play():
        config = MatchConfig(
            players=[
                {"name": "A", "tactician": "mcts", "config": {"simulations": 30}},
                {"name": "B", "tactician": "random"},
            ],
            seed=7,
            explainer=None,
        )
        return MatchRunner(config, keep_records=True).run()

    first, second = play(), play()
    assert first.scores == second.scores
    assert [r["action"] for r in first.records] == [r["action"] for r in second.records]


# -- Validator retry loop -----------------------------------------------------


class _IllegalOnce(Tactician):
    """Proposes an illegal move, then corrects itself using the violation."""

    def __init__(self):
        self.seen = []

    def decide(self, ctx):
        self.seen.append(ctx.violation)
        if ctx.violation is None:
            return Decision(Action(0, 0, 9))  # pattern row 9 does not exist
        return Decision(ctx.legal[0])


def test_retry_hands_the_violation_back_to_the_tactician():
    tactician = _IllegalOnce()
    pipeline = TurnPipeline(validator=Validator(), tacticians={0: tactician, 1: tactician})
    proposal = pipeline.propose(new_game(2, seed=1))
    assert tactician.seen[0] is None
    assert tactician.seen[1].predicate == "dest_exists"
    assert proposal.attempts == 2 and proposal.validation.ok


# -- winners and ties ---------------------------------------------------------


def test_aborted_match_has_no_winner():
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 5

    config = MatchConfig(
        players=[{"name": "Ann", "tactician": "greedy"}, {"name": "Bob", "tactician": "greedy"}],
        seed=1,
    )
    result = MatchRunner(config, stop_check=stop).run()
    assert result.winner is None and result.winner_name == ""


def _finished(scores, rows):
    state = GameState(num_players=len(scores))
    state.phase = "game_over"
    for board, score, full_rows in zip(state.players, scores, rows):
        board.score = score
        for r in range(full_rows):
            for c in range(5):
                board.wall |= 1 << (r * 5 + c)
    return state


def test_winner_breaks_score_ties_on_rows_then_shares():
    assert _finished([10, 12], [0, 0]).winner() == 1
    assert _finished([10, 10], [1, 0]).winner() == 0
    assert _finished([10, 10], [1, 1]).winner() is None  # shared victory


# -- state round-trip ---------------------------------------------------------


def test_json_round_trip_keeps_next_first_player():
    state = new_game(2, seed=3)
    step(state, legal_actions(state)[0])  # factory pick: tiles go to the center
    step(state, next(a for a in legal_actions(state) if a.from_center))
    assert state.next_first_player == 1
    assert GameState.from_dict(state.to_dict()).next_first_player == 1


# -- server -------------------------------------------------------------------


def test_importing_the_server_creates_no_database(tmp_path):
    subprocess.run(
        [sys.executable, "-c", "import tiles.server.app, tiles.server"],
        cwd=tmp_path,
        check=True,
        env={**os.environ, "PYTHONPATH": os.pathsep.join(sys.path)},
    )
    assert not (tmp_path / "db").exists()


def test_subscribe_replays_history_then_receives_new_events(tmp_path):
    manager = SessionManager(Ledger(tmp_path / "t.db"))
    session = manager.create(
        _local([{"name": "A", "tactician": "greedy"}, {"name": "B", "tactician": "greedy"}])
    )
    manager.publish(session, {"type": "log", "level": "info", "message": "before"})
    queue = manager.subscribe(session)
    assert queue.get_nowait()["message"] == "before"
    assert session.subscribers == [queue]
    manager.unsubscribe(session, queue)
    assert session.subscribers == []


def test_finished_sessions_are_evicted_beyond_the_cap(tmp_path):
    manager = SessionManager(Ledger(tmp_path / "t.db"))
    players = [{"name": "A", "tactician": "greedy"}, {"name": "B", "tactician": "greedy"}]
    ids = []
    for _ in range(MAX_FINISHED_IN_MEMORY + 3):
        session = manager.create(_local(players))
        ids.append(session.id)
        manager.set_status(session, "completed")
    assert len(manager.sessions) == MAX_FINISHED_IN_MEMORY
    assert ids[0] not in manager.sessions and ids[-1] in manager.sessions
    assert manager.summary(ids[0])["status"] == "completed"  # from the ledger


@pytest.mark.parametrize(
    "tactician, config, message",
    [
        ("mcts", {"simulations": 10_000_000}, "between"),
        ("mcts", {"simulations": "lots"}, "must be of type int"),
        ("minimax", {"depth": 2.5}, "must be of type int"),
        ("greedy", {"no_such_option": 1}, "invalid greedy config"),
    ],
)
def test_bad_tactician_config_is_rejected_at_creation(tactician, config, message):
    players = [
        {"name": "A", "tactician": tactician, "config": config},
        {"name": "B", "tactician": "greedy"},
    ]
    with pytest.raises(SessionError) as err:
        validate_session_config(_local(players))
    assert err.value.status_code == 422 and message in err.value.detail


def test_partial_greedy_weights_keep_the_defaults_for_the_rest():
    from tiles.agents.tacticians.greedy import GreedyTactician

    tactician = GreedyTactician(weights={"denial": 2.0})
    pipeline = TurnPipeline(validator=Validator(), tacticians={0: tactician, 1: tactician})
    assert pipeline.propose(new_game(2, seed=1)).validation.ok
    assert tactician.weights["denial"] == 2.0 and "immediate_points" in tactician.weights


def test_valid_tactician_config_is_accepted():
    validate_session_config(
        _local([
            {"name": "A", "tactician": "mcts", "config": {"simulations": 50, "c_puct": 2}},
            {"name": "B", "tactician": "greedy", "config": {"weights": {"denial": 2.0}}},
        ])
    )
