"""TD(0) reinforcement-learning player: features, update rule, learning and play."""

import asyncio
import random

import numpy as np
import pytest

from tiles.azul.game import new_game
from tiles.azul.rules import get_legal_actions
from tiles.ml.registry import registry
from tiles.ml.td_player import FEATURES, TDPlayer, features, td_update
from tiles.models.schemas import TileColor


def run(c):
    return asyncio.run(c)


def test_features_are_relative_and_have_the_right_shape():
    sim = new_game(["A", "B"], seed=1)
    f = features(sim.state, 0)
    assert f.shape == (len(FEATURES),) and f[-1] == 1.0              # bias
    assert np.allclose(f[:9], 0)                                     # symmetric empty boards: no difference
    sim.state.players[0].score = 25
    assert features(sim.state, 0)[0] == pytest.approx(0.5)           # (25 - 0) / 50
    assert features(sim.state, 1)[0] == pytest.approx(-0.5)          # the other player's view is the mirror


def test_features_see_pending_lines_progress_and_floor():
    sim = new_game(["A", "B"], seed=2)
    p = sim.state.players[0]
    p.pattern_lines[1] = [TileColor.RED, TileColor.RED]              # a complete line: points pending
    p.pattern_lines[3] = [TileColor.BLUE]                            # progress only
    p.floor_line = [TileColor.RED, TileColor.RED]
    f = features(sim.state, 0)
    names = dict(zip(FEATURES, f))
    assert names["pending_line_points"] > 0 and names["line_progress"] > 0 and names["floor_cost"] < 0


def test_td_update_moves_value_towards_the_target_and_terminal_case():
    w = np.zeros(3)
    phi = np.array([1.0, 0.0, 1.0])
    delta = td_update(w, phi, reward=1.0, next_phi=None, alpha=0.5)
    assert delta == 1.0 and np.allclose(w, [0.5, 0.0, 0.5])
    delta2 = td_update(w, phi, reward=0.0, next_phi=np.array([0.0, 1.0, 0.0]), alpha=0.5)
    assert delta2 == pytest.approx(-1.0) and w[0] < 0.5                  # bootstraps from the next state's value


def test_player_picks_highest_value_aftermove_and_explains():
    sim = new_game(["A", "B"], seed=3)
    w = np.zeros(len(FEATURES))
    w[FEATURES.index("floor_cost")] = 5.0                                # reward positions with LESS floor penalty
    p = TDPlayer(w=w)
    a = run(p.decide(sim.state, 0))
    assert a in get_legal_actions(sim.state, 0) and a.destination.value == "pattern_line"
    exp = p.last_explanation
    assert exp["model"] == "TDPlayer" and len(exp["top_alternatives"]) == 3 and p.last_phi.shape == (len(FEATURES),)
    assert p.value(sim.state, 0) == pytest.approx(float(w @ features(sim.state, 0)))


def test_epsilon_exploration_and_no_legal_moves():
    sim = new_game(["A", "B"], seed=4)
    explorer = TDPlayer(w=np.zeros(len(FEATURES)), epsilon=1.0, seed=1)
    assert {str(run(explorer.decide(sim.state, 0))) for _ in range(6)}.__len__() > 1
    sim.state.factories = [[] for _ in sim.state.factories]
    sim.state.center_pool = []
    with pytest.raises(ValueError):
        run(TDPlayer(w=np.zeros(len(FEATURES))).decide(sim.state, 0))


def test_save_load_roundtrip_and_registry(tmp_path):
    w = np.arange(len(FEATURES), dtype=float)
    path = tmp_path / "td.json"
    TDPlayer(w=w).save(path, meta={"games": 1})
    import json
    from tiles.ml import td_player
    td_player.DEFAULT_TD_PATH, old = path, td_player.DEFAULT_TD_PATH
    try:
        assert np.allclose(TDPlayer().w, w)
    finally:
        td_player.DEFAULT_TD_PATH = old
    assert json.loads(path.read_text())["features"] == FEATURES
    assert registry.create_player("TDPlayer").name == "TDPlayer"


def test_self_play_training_step_changes_weights_and_stays_finite():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import train_td

    w = np.zeros(len(FEATURES))
    err = run(train_td.self_play(w, random.Random(5), alpha=0.02, epsilon=0.2, vs_greedy=False))
    assert err > 0 and np.all(np.isfinite(w)) and np.abs(w).sum() > 0
    run(train_td.self_play(w, random.Random(6), alpha=0.02, epsilon=0.2, vs_greedy=True))
    assert np.all(np.isfinite(w))
