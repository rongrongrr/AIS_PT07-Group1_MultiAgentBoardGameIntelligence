"""Train the TD(0) value-function player by self-play, then evaluate it.

    python scripts/train_td.py --games 600 --seed 3

Self-play: two TDPlayers share one weight vector and learn after every move; the opponent is
sometimes a GreedyPlayer so the value function also sees positions against a different style.
Reward: change in score margin between a player's consecutive decisions (round scoring) plus the
final margin at the end of the game, scaled by 1/50. Evaluation plays the greedy (epsilon = 0)
policy against GreedyPlayer on unseen deals.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from duel import duel  # noqa: E402

from app.azul.game import apply_action, finish_game, new_game, round_over, step_round_boundary  # noqa: E402
from app.ml.greedy_player import GreedyPlayer  # noqa: E402
from app.ml.td_player import DEFAULT_TD_PATH, FEATURES, TDPlayer, td_update  # noqa: E402

REWARD_SCALE = 50.0


async def self_play(w: np.ndarray, rng: random.Random, alpha: float, epsilon: float, vs_greedy: bool) -> float:
    names = ["P0", "P1"]
    sim = new_game(names, seed=rng.randrange(10**9))
    learners = {0, 1} if not vs_greedy else {rng.choice([0, 1])}
    greedy = GreedyPlayer()
    td = TDPlayer(w=w, epsilon=epsilon, seed=rng.randrange(10**6))
    td.w = w                                        # share the live weight array
    prev = {i: None for i in learners}              # (phi, margin at that time)
    err = n = 0
    while not sim.finished:
        while not round_over(sim.state):
            idx = sim.current
            if idx in learners:
                margin = sim.state.players[idx].score - sum(
                    p.score for j, p in enumerate(sim.state.players) if j != idx)
                action = await td.decide(sim.state, idx)
                phi = td.last_phi
                if prev[idx] is not None:
                    p_phi, p_margin = prev[idx]
                    err += abs(td_update(w, p_phi, (margin - p_margin) / REWARD_SCALE, phi, alpha))
                    n += 1
                prev[idx] = (phi, margin)
            else:
                action = await greedy.decide(sim.state, idx)
            apply_action(sim, action)
        if step_round_boundary(sim):
            break
    for idx in learners:                            # terminal update with the final margin
        if prev[idx] is not None:
            p_phi, p_margin = prev[idx]
            final = sim.state.players[idx].score - sum(p.score for j, p in enumerate(sim.state.players) if j != idx)
            err += abs(td_update(w, p_phi, (final - p_margin) / REWARD_SCALE, None, alpha))
            n += 1
    return err / max(1, n)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=600)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--alpha", type=float, default=0.02)
    ap.add_argument("--eval-games", type=int, default=40)
    ap.add_argument("--mlflow", action="store_true")
    a = ap.parse_args()

    rng = random.Random(a.seed)
    w = np.zeros(len(FEATURES))
    t0 = time.time()
    curve = []
    for g in range(a.games):
        eps = max(0.05, 0.3 * (1 - g / a.games))
        alpha = a.alpha * (1 - 0.8 * g / a.games)
        e = await self_play(w, rng, alpha, eps, vs_greedy=(g % 3 == 0))
        curve.append(e)
        if (g + 1) % 50 == 0:
            print(f"  game {g + 1:4d}  mean |TD error| {np.mean(curve[-50:]):.4f}  ({time.time() - t0:.0f}s)", flush=True)

    player = TDPlayer(w=w)
    player.save(meta={"games": a.games, "seed": a.seed, "alpha": a.alpha})
    print("\nlearned weights:")
    for f, v in zip(FEATURES, w):
        print(f"  {f:<22}{v:+8.3f}")
    r = await duel(lambda: TDPlayer(w=w), GreedyPlayer, a.eval_games, a.seed + 5000)
    print(f"\nTDPlayer vs GreedyPlayer on unseen deals ({r['games']} games): win {r['win_rate']:.2f} "
          f"{r['ci95']} margin {r['mean_score_diff']:+.1f}")
    zero = await duel(lambda: TDPlayer(w=np.zeros(len(FEATURES))), GreedyPlayer, a.eval_games // 2, a.seed + 5000)
    print(f"untrained (all-zero value) vs GreedyPlayer: win {zero['win_rate']:.2f} margin {zero['mean_score_diff']:+.1f}")
    if a.mlflow:
        from app import tracking
        tracking.log_run(tracking.EVALUATION_EXPERIMENT, "td reinforcement learning",
                         params={"games": a.games, "alpha": a.alpha, "seed": a.seed},
                         metrics={"win_rate_vs_greedy": r["win_rate"], "margin_vs_greedy": r["mean_score_diff"],
                                  **{f"w.{f}": float(v) for f, v in zip(FEATURES, w)}},
                         series={"mean_abs_td_error": [float(np.mean(curve[max(0, i - 49):i + 1])) for i in range(0, len(curve), 10)]},
                         tags={"kind": "rl"})


if __name__ == "__main__":
    asyncio.run(main())
