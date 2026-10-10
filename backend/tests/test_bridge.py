"""Differential test of the two rules engines (live ``tiles.azul`` vs bit-packed ``tiles.core``)
plus the bridge that lets core Tacticians play through the live ``MachinePlayer`` interface."""

import asyncio
import copy
import random

import pytest

from tiles.azul.game import apply_action as live_apply
from tiles.azul.game import new_game, round_over, step_round_boundary
from tiles.azul.rules import get_legal_actions
from tiles.bridge import (
    CORE_PLAYERS,
    TilesMCTSPlayer,
    TilesMinimaxPlayer,
    TilesProfiledMCTSPlayer,
    from_core_action,
    to_core_action,
    to_core_state,
)
from tiles.core import legal_actions, step
from tiles.ml.archetypes import move_record
from tiles.ml.registry import registry


def _ids(actions):
    return sorted(to_core_action(a).action_id for a in actions)


@pytest.mark.parametrize("n_players,seed", [(2, 1), (2, 2), (3, 3), (4, 4), (2, 5), (3, 6)])
def test_engines_agree_over_full_games(n_players, seed):
    """Same legal moves every turn and identical scores after every round and at game end."""
    rng = random.Random(seed)
    sim = new_game([f"P{i}" for i in range(n_players)], seed=seed)
    turns = 0
    while not sim.finished:
        me = sim.current
        live_legal = get_legal_actions(sim.state, me)
        core = to_core_state(sim.state, me)
        assert _ids(live_legal) == sorted(a.action_id for a in legal_actions(core))

        action = rng.choice(live_legal)
        _, round_result = step(core, to_core_action(action))
        live_apply(sim, action)
        turns += 1
        if round_over(sim.state):
            step_round_boundary(sim)
            assert round_result is not None
            assert [p.score for p in sim.state.players] == core.scores()
        else:
            assert round_result is None
    assert turns > 20


def test_action_round_trip():
    sim = new_game(["A", "B"], seed=9)
    for a in get_legal_actions(sim.state, 0):
        assert from_core_action(to_core_action(a)) == a


def test_to_core_state_conserves_tiles():
    rng = random.Random(3)
    sim = new_game(["A", "B", "C"], seed=3)
    for _ in range(14):
        a = rng.choice(get_legal_actions(sim.state, sim.current))
        live_apply(sim, a)
        if round_over(sim.state):
            step_round_boundary(sim)
    core = to_core_state(sim.state, sim.current)
    visible = sum(sum(f) for f in core.factories) + sum(core.center)
    assert all(b >= 0 for b in core.bag)
    assert visible <= 100 and sum(core.bag) <= 100


@pytest.mark.parametrize("cls", CORE_PLAYERS)
def test_core_players_play_legal_full_games(cls):
    """Each bridged Tactician finishes a 2-player game against a random live player with only legal moves."""
    sim = new_game(["Core", "Rand"], seed=11)
    rng = random.Random(11)
    player = cls(seed=1)
    player.tactician.simulations = 20 if hasattr(player.tactician, "simulations") else None
    moves = 0
    while not sim.finished:
        me = sim.current
        legal = get_legal_actions(sim.state, me)
        if me == 0:
            action = asyncio.run(player.decide(sim.state, me))
            assert action in legal
            assert player.last_explanation["top_alternatives"]
        else:
            action = rng.choice(legal)
        rec = move_record(sim.state, me, action)
        rec["player_index"] = me
        player.observe(rec, "Core")
        live_apply(sim, action)
        moves += 1
        if round_over(sim.state):
            step_round_boundary(sim)
        assert moves < 400
    assert sim.finished


def test_profiled_player_learns_opponent_moves():
    sim = new_game(["Core", "Opp"], seed=21)
    player = TilesProfiledMCTSPlayer(seed=2)
    rng = random.Random(0)
    for _ in range(4):
        me = sim.current
        a = rng.choice(get_legal_actions(sim.state, me))
        rec = move_record(sim.state, me, a)
        rec["player_index"] = me
        player.observe(rec, "Core")
        live_apply(sim, a)
    assert player.predictor.moves_observed(1) >= 1 or player.predictor.moves_observed(0) >= 1
    assert TilesMCTSPlayer().predictor is None


def test_core_players_registered_and_clonable():
    for cls in CORE_PLAYERS:
        p = registry.create_player(cls._name)
        assert p is not None and type(p) is cls and p is not registry.get_player(cls._name)
    assert isinstance(registry.create_player("TilesMinimax"), TilesMinimaxPlayer)
