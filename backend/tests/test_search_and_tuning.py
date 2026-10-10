"""MCTS, Elo tournament, GA tuning, and ledger-record conversion."""

import asyncio

import pytest

from app.azul.game import new_game, play_game
from app.azul.rules import get_legal_actions
from app.ml.archetypes import move_record, state_from_record
from app.ml.elo import EloRatings, round_robin
from app.ml.greedy_player import BlockerPlayer, DEFAULT_WEIGHTS, GreedyPlayer, Weights
from app.ml.mcts_player import ConditionedMCTSPlayer, MCTSPlayer
from app.ml.random_player import RandomPlayer
from app.ml.registry import registry
from app.ml.tuning import BOUNDS, GENES, clip, evaluate, evolve, to_genome, to_weights


def run(c):
    return asyncio.run(c)


# ------------------------------------------------------------------ record <-> state

def test_state_from_record_roundtrips_the_board():
    sim = new_game(["A", "B"], seed=3)
    sim.state.players[0].pattern_lines[2] = [sim.state.factories[0][0]] * 2
    sim.state.players[1].wall[1][1] = True
    action = get_legal_actions(sim.state, 0)[0]
    rebuilt = state_from_record(move_record(sim.state, 0, action))
    assert rebuilt.factories == sim.state.factories and rebuilt.center_pool == sim.state.center_pool
    assert [p.pattern_lines for p in rebuilt.players] == [p.pattern_lines for p in sim.state.players]
    assert rebuilt.players[1].wall == sim.state.players[1].wall
    assert get_legal_actions(rebuilt, 0) == get_legal_actions(sim.state, 0)
    assert state_from_record({"no": "board"}) is None
    assert state_from_record({"board": {"factories": [["purple"]], "center_pool": [], "players": []}}) is None


# ------------------------------------------------------------------ MCTS

def test_mcts_legal_deterministic_and_explains():
    sim = new_game(["A", "B"], seed=3)
    p1, p2 = MCTSPlayer(iterations=60, seed=4), MCTSPlayer(iterations=60, seed=4)
    a1, a2 = run(p1.decide(sim.state, 0)), run(p2.decide(sim.state, 0))
    assert a1 in get_legal_actions(sim.state, 0) and a1 == a2
    exp = p1.last_explanation
    assert "UCT" in exp["method"] and exp["top_alternatives"][0]["visits"] >= exp["top_alternatives"][-1]["visits"]


def test_mcts_does_not_mutate_input_and_raises_without_moves():
    sim = new_game(["A", "B"], seed=5)
    before = sim.state.model_dump_json()
    run(MCTSPlayer(iterations=30, seed=1).decide(sim.state, 0))
    assert sim.state.model_dump_json() == before
    sim.state.factories = [[] for _ in sim.state.factories]
    sim.state.center_pool = []
    with pytest.raises(ValueError):
        run(MCTSPlayer().decide(sim.state, 0))


def test_mcts_beats_greedy_over_games():
    wins = 0
    for seed in range(3):
        ps = [MCTSPlayer(iterations=60, seed=seed), GreedyPlayer()]
        r = run(play_game([p.decide for p in ps], ["M", "G"], seed=seed))
        assert r["ended_naturally"]
        wins += r["scores"]["M"] > r["scores"]["G"]
    assert wins >= 2


def test_conditioned_mcts_learns_opponent_style_and_uses_it():
    me = ConditionedMCTSPlayer(iterations=40, seed=2, min_observed=4)
    opp = BlockerPlayer()
    players = [me, opp]
    run(play_game([p.decide for p in players], ["Me", "Opp"], seed=6,
                  observers=[getattr(p, "observe", None) for p in players], max_rounds=2))
    assert me._models["Opp"].observed >= 4
    sim = new_game(["Me", "Opp"], seed=1)
    run(me.decide(sim.state, 0))
    assert "adaptation" in me.last_explanation
    assert registry.create_player("ConditionedMCTSPlayer").conditioned is True
    plain = MCTSPlayer(iterations=10)
    plain.observe({"player_name": "x", "action": {}, "board": None}, "me")        # ignored when not conditioned
    assert plain._models == {}


def test_conditioned_mcts_ignores_own_moves_and_unreadable_records():
    p = ConditionedMCTSPlayer(iterations=10)
    p.observe({"player_name": "me", "action": {}, "board": {}}, "me")
    p.observe({"player_name": "x", "action": {}, "board": None}, "me")
    assert p._models == {}


# ------------------------------------------------------------------ Elo

def test_elo_update_rules():
    e = EloRatings()
    assert e.expected(1500, 1500) == 0.5 and e.expected(1900, 1500) > 0.9
    e.update("a", "b", 1.0)
    assert e.get("a") > 1500 > e.get("b") and abs(e.get("a") + e.get("b") - 3000) < 1e-9
    e.update("a", "b", 0.5)
    assert abs(e.get("a") + e.get("b") - 3000) < 1e-9


def test_round_robin_ranks_players_by_strength():
    res = run(round_robin({"Random": lambda s: RandomPlayer(seed=s), "Greedy": lambda s: GreedyPlayer(),
                           "Blocker": lambda s: BlockerPlayer()}, deals=3, seed=2))
    assert res.n_games == 3 * 3 * 2
    ranking = [n for n, _ in res.ranking()]
    assert ranking[-1] == "Random" and res.elo["Greedy"] > res.elo["Random"]
    assert res.win_rate("Greedy", "Random") > 0.9 and abs(res.win_rate("Greedy", "Random") + res.win_rate("Random", "Greedy") - 1) < 1e-9
    assert res.mean_score["Greedy"] > res.mean_score["Random"]


# ------------------------------------------------------------------ GA tuning

def test_genome_conversion_and_clipping():
    g = to_genome(DEFAULT_WEIGHTS)
    assert to_weights(g) == DEFAULT_WEIGHTS and len(g) == len(GENES)
    wild = clip([1e9] * len(GENES))
    assert all(v == BOUNDS[name][1] for name, v in zip(GENES, wild))
    assert all(v == BOUNDS[name][0] for name, v in zip(GENES, clip([-1e9] * len(GENES))))


def test_fitness_prefers_a_stronger_player():
    deals = [1, 2]
    good = run(evaluate(DEFAULT_WEIGHTS, [lambda: RandomPlayer(seed=1)], deals))
    bad = run(evaluate(Weights(wall=0.5, fill=0.0, row_pref=0.0, bonus=0.0, overflow=0.0, floor=0.1, volume=2.0),
                       [lambda: GreedyPlayer()], deals))
    assert good > bad


def test_evolve_returns_valid_weights_and_history():
    seen = []
    res = run(evolve([lambda: RandomPlayer(seed=3)], population=4, generations=2, deals_per_eval=1, seed=1,
                     on_generation=lambda g, b, m: seen.append(g)))
    assert len(res.history) == 2 and seen == [0, 1] and res.history[0]["best"] >= res.history[0]["mean"]
    for g, v in zip(GENES, to_genome(res.best)):
        assert BOUNDS[g][0] <= v <= BOUNDS[g][1]


def test_conditioned_minimax_infers_style_and_orders_replies_by_it():
    from app.ml.minimax_player import ConditionedMinimaxPlayer

    me = ConditionedMinimaxPlayer(depth=2, min_observed=4)
    players = [me, BlockerPlayer()]
    run(play_game([p.decide for p in players], ["Me", "Opp"], seed=7,
                  observers=[getattr(p, "observe", None) for p in players], max_rounds=2))
    assert me._models["Opp"].observed >= 4
    sim = new_game(["Me", "Opp"], seed=2)
    a = run(me.decide(sim.state, 0))
    assert a in get_legal_actions(sim.state, 0)
    assert "adaptation" in me.last_explanation and registry.create_player("ConditionedMinimaxPlayer")
    me.observe({"player_name": "Me", "action": {}, "board": {}}, "Me")             # own moves ignored
    me.observe({"player_name": "X", "action": {}, "board": None}, "Me")            # unreadable record ignored
    assert "X" not in me._models
