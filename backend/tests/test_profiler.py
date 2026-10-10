"""Profiler module tests: archetypes, traits, prediction, learning."""

import random

from tiles.agents.base import DecisionContext
from tiles.agents.profiler import (
    ARCHETYPES,
    BasicProfiler,
    KMeans,
    OpponentMovePredictor,
    classify,
)
from tiles.agents.tacticians.greedy import GreedyTactician
from tiles.core import deal_round, legal_actions, new_game, step
from tiles.sim.prediction_eval import (
    BLOCKER_WEIGHTS,
    evaluate_prediction_accuracy,
)


# ---------------------------------------------------------------------------
# Archetype classification
# ---------------------------------------------------------------------------


def test_classify_high_denial_is_aggressive_blocker():
    traits = {
        "color_bias": 0.08,
        "center_rate": 0.55,
        "floor_rate": 0.30,
        "completion_rate": 0.55,
        "denial_avg": 0.35,
        "risk_avg": 0.32,
        "bonus_focus": 0.40,
        "fpt_rate": 0.20,
        "immediate_avg": 0.35,
    }
    archetype, confidence = classify(traits)
    assert archetype == "aggressive_blocker"
    assert 0.0 < confidence <= 1.0
    # winner's confidence must beat every alternative's softmax share
    assert confidence > (1.0 - confidence) / (len(ARCHETYPES) - 1)


def test_classify_low_risk_completer_is_cautious_optimizer():
    traits = {
        "color_bias": 0.08,
        "center_rate": 0.40,
        "floor_rate": 0.05,
        "completion_rate": 0.78,
        "denial_avg": 0.08,
        "risk_avg": 0.06,
        "bonus_focus": 0.45,
        "fpt_rate": 0.05,
        "immediate_avg": 0.50,
    }
    archetype, _ = classify(traits)
    assert archetype == "cautious_optimizer"


# ---------------------------------------------------------------------------
# End-to-end profiling of a simulated game
# ---------------------------------------------------------------------------


def play_game(profiler, tacticians, seed=0, collect_for=None):
    """Play one full game, feeding the profiler; optionally collect
    (state_before, legal, action) triples for ``collect_for`` player."""
    state = new_game(len(tacticians), seed=seed)
    rng = random.Random(seed)
    collected = []
    while not state.is_game_over:
        mover = state.current_player
        legal = legal_actions(state)
        decision = tacticians[mover].decide(
            DecisionContext(state=state, player_index=mover, legal=legal)
        )
        state_before = state.clone()
        if collect_for is not None and mover == collect_for:
            collected.append((state_before, legal, decision.action))
        move, round_result = step(state, decision.action)
        if profiler is not None:
            profiler.observe(state_before, decision.action, move, decision_ms=50)
        if round_result is not None and not round_result.game_over:
            deal_round(state, rng)
    return collected


def test_basic_profiler_builds_profiles_from_game():
    profiler = BasicProfiler()
    play_game(profiler, [GreedyTactician(), GreedyTactician()], seed=3)
    for i in range(2):
        profile = profiler.profile(i)
        assert profile.moves_observed > 0
        assert profile.archetype in ARCHETYPES
        assert profile.summary
        assert 0.0 < profile.confidence <= 1.0
        assert set(profile.traits) >= {
            "color_bias",
            "floor_rate",
            "completion_rate",
            "denial_avg",
        }
        assert profile.to_dict()["archetype"] == profile.archetype


def test_predict_returns_distribution_over_legal_actions():
    profiler = BasicProfiler()
    state = new_game(2, seed=11)
    legal = legal_actions(state)
    dist = profiler.predict(state, 0, legal)
    assert set(dist) == {a.action_id for a in legal}
    assert abs(sum(dist.values()) - 1.0) < 1e-9
    assert all(p >= 0 for p in dist.values())


# ---------------------------------------------------------------------------
# Learning: predictor beats the uniform baseline on held-out moves
# ---------------------------------------------------------------------------


def test_predictor_learns_denial_heavy_player():
    blocker = GreedyTactician(BLOCKER_WEIGHTS)
    opponent = GreedyTactician()
    # Collect the blocker's moves across two games.
    triples = []
    for seed in (21, 22):
        triples += play_game(
            None, [blocker, opponent], seed=seed, collect_for=0
        )
    assert len(triples) >= 40
    train, held_out = triples[:-10], triples[-10:]

    predictor = OpponentMovePredictor()
    for state_before, _, action in train:
        predictor.observe(state_before, action, player_index=0)

    hits = 0
    uniform_expectation = 0.0
    for state_before, legal, action in held_out:
        top3 = predictor.top_k(state_before, 0, legal, k=3)
        hits += int(action.action_id in top3)
        uniform_expectation += min(3, len(legal)) / len(legal)
    assert hits / 10 > uniform_expectation / 10


# ---------------------------------------------------------------------------
# KMeans
# ---------------------------------------------------------------------------


def test_kmeans_recovers_two_separated_clusters():
    rng = random.Random(5)
    cluster_a = [
        [0.1 + rng.uniform(-0.05, 0.05), 0.1 + rng.uniform(-0.05, 0.05)]
        for _ in range(20)
    ]
    cluster_b = [
        [0.9 + rng.uniform(-0.05, 0.05), 0.9 + rng.uniform(-0.05, 0.05)]
        for _ in range(20)
    ]
    km = KMeans().fit(cluster_a + cluster_b, k=2, seed=1)
    labels_a = {km.predict(v) for v in cluster_a}
    labels_b = {km.predict(v) for v in cluster_b}
    assert len(labels_a) == 1 and len(labels_b) == 1
    assert labels_a != labels_b


# ---------------------------------------------------------------------------
# End-to-end evaluation harness
# ---------------------------------------------------------------------------


def test_prediction_eval_runs_and_beats_uniform():
    results = evaluate_prediction_accuracy(games=3, seed=1)
    assert results["n_predictions"] > 0
    assert results["predictor"]["top3"] >= results["uniform"]["top3"]
    assert len(results["archetypes"]) == 3
    for row in results["archetypes"]:
        assert row["archetype"] in ARCHETYPES
