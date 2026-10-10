"""MinimaxPlayer: legality, explanation, search behaviour."""

import asyncio

import pytest

from app.azul.game import new_game, play_game
from app.azul.rules import get_legal_actions
from app.ml.greedy_player import GreedyPlayer
from app.ml.minimax_player import MinimaxPlayer
from app.ml.registry import registry
from app.ml.rollout_player import ValueWeights


def run(c):
    return asyncio.run(c)


def test_decides_a_legal_move_and_explains_the_search():
    sim = new_game(["A", "B"], seed=3)
    p = MinimaxPlayer(depth=2)
    a = run(p.decide(sim.state, 0))
    assert a in get_legal_actions(sim.state, 0)
    assert "alpha-beta depth 2" in p.last_explanation["method"] and p.nodes > 0
    scores = [x["score"] for x in p.last_explanation["top_alternatives"]]
    assert scores == sorted(scores, reverse=True)


def test_deterministic_and_does_not_mutate_input():
    sim = new_game(["A", "B"], seed=5)
    before = sim.state.model_dump_json()
    a1 = run(MinimaxPlayer(depth=2).decide(sim.state, 0))
    a2 = run(MinimaxPlayer(depth=2).decide(sim.state, 0))
    assert a1 == a2 and sim.state.model_dump_json() == before


def test_raises_without_legal_moves():
    sim = new_game(["A", "B"], seed=1)
    sim.state.factories = [[] for _ in sim.state.factories]
    sim.state.center_pool = []
    with pytest.raises(ValueError):
        run(MinimaxPlayer().decide(sim.state, 0))


def test_time_budget_zero_still_returns_a_move():
    sim = new_game(["A", "B"], seed=2)
    p = MinimaxPlayer(depth=3, time_budget_s=0.0)
    assert run(p.decide(sim.state, 0)) in get_legal_actions(sim.state, 0)


def test_three_player_search_and_registry():
    sim = new_game(["A", "B", "C"], seed=4)
    p = MinimaxPlayer(depth=2, beam=3, value=ValueWeights(opponent=0.5))
    assert run(p.decide(sim.state, 0)) in get_legal_actions(sim.state, 0)
    assert registry.create_player("MinimaxPlayer").name == "MinimaxPlayer"


def test_beats_greedy_over_full_games():
    wins = 0
    for seed in range(3):
        ps = [MinimaxPlayer(depth=2), GreedyPlayer()]
        r = run(play_game([p.decide for p in ps], ["M", "G"], seed=seed))
        assert r["ended_naturally"]
        wins += r["scores"]["M"] > r["scores"]["G"]
    assert wins >= 2
