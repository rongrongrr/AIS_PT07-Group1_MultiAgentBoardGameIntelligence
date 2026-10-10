"""PettingZoo env tests (skipped unless the rl extra is installed)."""

import pytest

pettingzoo = pytest.importorskip("pettingzoo")


def test_azul_env_full_random_game():
    import numpy as np

    from tiles.rl.azul_env import env

    game = env(num_players=2, seed=5)
    game.reset(seed=5)
    rng = np.random.default_rng(5)
    steps = 0
    for agent in game.agent_iter(max_iter=2000):
        obs, reward, termination, truncation, info = game.last()
        if termination or truncation:
            game.step(None)
            continue
        mask = obs["action_mask"]
        assert mask.sum() > 0
        legal_ids = np.flatnonzero(mask)
        game.step(int(rng.choice(legal_ids)))
        steps += 1
    assert steps > 20
    assert all(game.terminations.values())


def test_azul_env_api_compliance():
    from pettingzoo.test import api_test

    from tiles.rl.azul_env import env

    api_test(env(num_players=2, seed=1), num_cycles=30)
