"""Tests for tiles.azul.game (state transitions and full-game simulation)."""

import asyncio

import pytest

from tiles.azul.game import (
    FIRST_PLAYER, apply_action, floor_size, new_game, play_game, step_round_boundary,
)
from tiles.ml.greedy_player import GreedyPlayer
from tiles.ml.random_player import RandomPlayer
from tiles.models.schemas import DestinationType, GameAction, SourceType, TileColor


def tile_total(sim) -> int:
    s = sim.state
    n = len(sim.bag) + len(sim.lid)
    n += sum(len(f) for f in s.factories)
    n += sum(1 for t in s.center_pool if t != FIRST_PLAYER)
    for p in s.players:
        n += sum(len(r) for r in p.pattern_lines) + len(p.floor_line)
        n += sum(sum(r) for r in p.wall)
    return n


def test_new_game_deals_full_factories():
    sim = new_game(["A", "B"], seed=1)
    assert len(sim.state.factories) == 5
    assert all(len(f) == 4 for f in sim.state.factories)
    assert sim.state.center_pool == [FIRST_PLAYER]
    assert tile_total(sim) == 100


def test_taking_from_center_gives_token_and_counts_toward_floor():
    sim = new_game(["A", "B"], seed=1)
    sim.state.center_pool = ["red", "red", FIRST_PLAYER]
    act = GameAction(source_type=SourceType.CENTER, color=TileColor.RED,
                     destination=DestinationType.PATTERN_LINE, destination_row=2)
    apply_action(sim, act)
    p = sim.state.players[0]
    assert p.has_first_player_token
    assert floor_size(p) == 1
    assert FIRST_PLAYER not in sim.state.center_pool
    assert len(p.pattern_lines[2]) == 2


def test_token_holder_starts_next_round():
    sim = new_game(["A", "B"], seed=3)
    sim.state.players[1].has_first_player_token = True
    sim.state.factories = [[] for _ in sim.state.factories]
    sim.state.center_pool = []
    step_round_boundary(sim)
    assert sim.current == 1


def test_same_seed_same_game():
    async def run(seed):
        ps = [GreedyPlayer(), RandomPlayer(seed=seed)]
        return await play_game([p.decide for p in ps], ["G", "R"], seed=seed)
    assert asyncio.run(run(5)) == asyncio.run(run(5))


@pytest.mark.parametrize("n_players", [2, 3, 4])
def test_tiles_conserved_through_full_game(n_players):
    names = [f"P{i}" for i in range(n_players)]
    players = [RandomPlayer(seed=i) for i in range(n_players)]
    totals = []

    def hook(sim, idx, action):
        totals.append(tile_total(sim))

    res = asyncio.run(play_game([p.decide for p in players], names, seed=11, on_move=hook))
    assert res["ended_naturally"]
    assert set(totals) == {100}


def test_greedy_beats_random_over_many_seeds():
    wins = 0
    for seed in range(20):
        ps = [GreedyPlayer(), RandomPlayer(seed=seed)]
        r = asyncio.run(play_game([p.decide for p in ps], ["G", "R"], seed=seed))
        wins += r["scores"]["G"] > r["scores"]["R"]
    assert wins >= 18
