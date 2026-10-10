"""RolloutPlayer / AdaptiveRolloutPlayer behaviour and strength sanity checks."""

import asyncio

import pytest

from app.azul.game import apply_action, new_game, play_game
from app.azul.rules import get_legal_actions
from app.ml.adaptive_player import AdaptiveRolloutPlayer
from app.ml.archetypes import Prediction
from app.ml.greedy_player import ARCHETYPES, DEFAULT_WEIGHTS, GreedyPlayer
from app.ml.random_player import RandomPlayer
from app.ml.registry import registry
from app.ml.rollout_player import RolloutPlayer, potential
from app.models.schemas import PlayerState, TileColor


def run(c):
    return asyncio.run(c)


def test_potential_rewards_progress_and_ignores_empty_board():
    empty = PlayerState(index=0, name="a")
    assert potential(empty) == 0
    partial = PlayerState(index=0, name="a", pattern_lines=[[], [TileColor.RED], [], [], []])
    assert potential(partial) > 0
    wall = [[False] * 5 for _ in range(5)]
    wall[0][0] = wall[1][1] = wall[2][2] = True
    assert potential(PlayerState(index=0, name="a", wall=wall)) > 0


def test_decides_legal_move_and_explains_itself():
    sim = new_game(["A", "B"], seed=3)
    p = RolloutPlayer(seed=1)
    a = run(p.decide(sim.state, 0))
    assert a in get_legal_actions(sim.state, 0)
    exp = p.last_explanation
    assert exp["model"] == "RolloutPlayer" and "rollouts" in exp["method"]
    scores = [x["score"] for x in exp["top_alternatives"]]
    assert scores == sorted(scores, reverse=True)


def test_raises_when_no_legal_moves():
    sim = new_game(["A", "B"], seed=1)
    sim.state.factories = [[] for _ in sim.state.factories]
    sim.state.center_pool = []
    with pytest.raises(ValueError):
        run(RolloutPlayer(seed=1).decide(sim.state, 0))


def test_time_budget_still_returns_a_move():
    sim = new_game(["A", "B"], seed=2)
    p = RolloutPlayer(seed=1, time_budget_s=0.0)
    assert run(p.decide(sim.state, 0)) in get_legal_actions(sim.state, 0)


def test_same_seed_same_decision():
    sim = new_game(["A", "B"], seed=5)
    a1 = run(RolloutPlayer(seed=9).decide(sim.state, 0))
    a2 = run(RolloutPlayer(seed=9).decide(sim.state, 0))
    assert a1 == a2


def test_does_not_mutate_the_state_it_is_given():
    sim = new_game(["A", "B"], seed=4)
    before = sim.state.model_dump_json()
    run(RolloutPlayer(seed=1).decide(sim.state, 0))
    assert sim.state.model_dump_json() == before


def test_plays_full_games_legally_and_beats_greedy():
    wins = 0
    for seed in range(4):
        players = [RolloutPlayer(seed=seed), GreedyPlayer()]
        r = run(play_game([p.decide for p in players], ["R", "G"], seed=seed))
        assert r["ended_naturally"]
        wins += r["scores"]["R"] > r["scores"]["G"]
    assert wins >= 3                        # measured: 100% over 60 games


def test_registered_and_instantiable_per_game():
    for name in ("RolloutPlayer", "AdaptiveRolloutPlayer"):
        a, b = registry.create_player(name), registry.create_player(name)
        assert a is not b and a.name == name


class FakeClassifier:
    def __init__(self, label, confidence):
        self.label, self.confidence = label, confidence

    def predict(self, feats):
        return Prediction(self.label, self.confidence, {self.label: self.confidence}, [])


def observe_some(player, n=12):
    other = RandomPlayer(seed=1)
    players = [player, other]
    run(play_game([p.decide for p in players], ["Me", "Opp"], seed=2,
                  observers=[getattr(p, "observe", None) for p in players], max_rounds=1))


def test_adaptive_rollout_simulates_opponent_as_inferred_archetype():
    p = AdaptiveRolloutPlayer(classifier=FakeClassifier("BlockerPlayer", 0.9), seed=1)
    p.MIN_OBSERVED_MOVES = 3
    observe_some(p)
    sim = new_game(["Me", "Opp"], seed=1)
    weights = p.opponent_weights(sim.state)
    assert weights == {"Opp": ARCHETYPES["BlockerPlayer"]}
    run(p.decide(sim.state, 0))
    assert "Opp ~ BlockerPlayer" in p.last_explanation["adaptation"]["reason"]


def test_adaptive_rollout_ignores_low_confidence_labels():
    p = AdaptiveRolloutPlayer(classifier=FakeClassifier("BlockerPlayer", 0.2), seed=1)
    p.MIN_OBSERVED_MOVES = 3
    observe_some(p)
    sim = new_game(["Me", "Opp"], seed=1)
    assert p.opponent_weights(sim.state) == {}
    run(p.decide(sim.state, 0))
    assert "not enough" in p.last_explanation["adaptation"]["reason"]
