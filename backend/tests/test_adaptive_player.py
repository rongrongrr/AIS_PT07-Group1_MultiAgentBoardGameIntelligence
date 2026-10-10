"""Tests for AdaptivePlayer, observer plumbing, and move explanations."""

import asyncio

from tiles.azul.game import new_game, play_game
from tiles.ml.adaptive_player import AdaptivePlayer
from tiles.ml.archetypes import Prediction
from tiles.ml.greedy_player import COUNTER_STYLES, GreedyPlayer
from tiles.ml.random_player import RandomPlayer
from tiles.ml.registry import registry


class FakeClassifier:
    """Always says the opponent is a 'RecklessPlayer'."""

    def predict(self, feats):
        return Prediction("RecklessPlayer", 0.9, {"RecklessPlayer": 0.9}, [])


def _play(players, seed=1):
    names = [f"P{i}" for i in range(len(players))]
    return asyncio.run(play_game(
        [p.decide for p in players], names, seed=seed,
        observers=[p.observe for p in players],
    ))


def test_adaptive_plays_full_game_legally():
    res = _play([AdaptivePlayer(), RandomPlayer(seed=1)])
    assert res["ended_naturally"]


def test_defaults_to_balanced_before_enough_observations():
    p = AdaptivePlayer(classifier=FakeClassifier(), best_response={"RecklessPlayer": "HeavyBlocker"})
    weights, info = p.choose_weights()
    assert weights == COUNTER_STYLES["Balanced"]
    assert info["playing_as"] == "Balanced"


def test_switches_style_once_opponent_is_classified():
    me = AdaptivePlayer(classifier=FakeClassifier(), best_response={"RecklessPlayer": "HeavyBlocker"})
    opp = RandomPlayer(seed=2)
    _play([me, opp], seed=4)
    weights, info = me.choose_weights()
    assert info["target_archetype"] == "RecklessPlayer"
    assert weights == COUNTER_STYLES["HeavyBlocker"]


def test_observe_ignores_own_moves():
    p = AdaptivePlayer(classifier=FakeClassifier(), best_response={})
    p.observe({"player_name": "me"}, "me")
    p.observe({"player_name": "them"}, "me")
    assert list(p.history) == ["them"]


def test_decision_records_explanation_with_alternatives():
    sim = new_game(["A", "B"], seed=3)
    g = GreedyPlayer()
    asyncio.run(g.decide(sim.state, 0))
    exp = g.last_explanation
    assert exp["model"] == "GreedyPlayer"
    assert 1 <= len(exp["top_alternatives"]) <= 3
    scores = [a["score"] for a in exp["top_alternatives"]]
    assert scores == sorted(scores, reverse=True)
    assert exp["chosen_score"] == scores[0]


def test_registry_creates_independent_instances():
    a = registry.create_player("AdaptivePlayer")
    b = registry.create_player("AdaptivePlayer")
    assert a is not b and a.history is not b.history
    assert registry.create_player("NoSuchPlayer") is None
