"""Round-robin tournament with Elo ratings, win-rate matrix and score statistics.

    python scripts/elo_tournament.py --deals 10 --seed 3
    python scripts/elo_tournament.py --deals 10 --players RandomPlayer GreedyPlayer MinimaxPlayer --mlflow

Every pair plays the same deals from both seats. Elo comes from replaying all results in random
order several times and averaging (so it does not depend on game order).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ml.elo import round_robin  # noqa: E402
from app.ml.greedy_player import BlockerPlayer, ColorCollectorPlayer, GreedyPlayer, RecklessPlayer, RusherPlayer  # noqa: E402
from app.ml.mcts_player import MCTSPlayer  # noqa: E402
from app.ml.minimax_player import MinimaxPlayer  # noqa: E402
from app.ml.random_player import RandomPlayer  # noqa: E402
from app.ml.rollout_player import RolloutPlayer  # noqa: E402
from app.ml.td_player import TDPlayer  # noqa: E402

FACTORIES = {
    "RandomPlayer": lambda s: RandomPlayer(seed=s),
    "GreedyPlayer": lambda s: GreedyPlayer(),
    "RusherPlayer": lambda s: RusherPlayer(),
    "RecklessPlayer": lambda s: RecklessPlayer(),
    "ColorCollectorPlayer": lambda s: ColorCollectorPlayer(),
    "BlockerPlayer": lambda s: BlockerPlayer(),
    "RolloutPlayer": lambda s: RolloutPlayer(seed=s),
    "MinimaxPlayer": lambda s: MinimaxPlayer(),
    "MCTSPlayer": lambda s: MCTSPlayer(seed=s, iterations=120),
    "TDPlayer": lambda s: TDPlayer(),
}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deals", type=int, default=8, help="deals per pair (each played from both seats)")
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--players", nargs="+", default=["RandomPlayer", "GreedyPlayer", "BlockerPlayer", "RolloutPlayer", "MinimaxPlayer"],
                    choices=list(FACTORIES))
    ap.add_argument("--mlflow", action="store_true")
    a = ap.parse_args()

    res = await round_robin({n: FACTORIES[n] for n in a.players}, a.deals, a.seed)
    print(f"{res.n_games} games\n")
    print(f"{'rank':<5}{'player':<22}{'Elo':>8}{'mean score':>12}")
    for i, (name, elo) in enumerate(res.ranking(), 1):
        print(f"{i:<5}{name:<22}{elo:>8.0f}{res.mean_score[name]:>12.1f}")
    names = [n for n, _ in res.ranking()]
    print("\nwin rate of ROW against COLUMN")
    print(f"{'':<22}" + "".join(f"{n[:9]:>10}" for n in names))
    for r in names:
        print(f"{r:<22}" + "".join(f"{'-':>10}" if r == c else f"{res.win_rate(r, c):>10.2f}" for c in names))
    if a.mlflow:
        from app import tracking
        tracking.log_run(tracking.EVALUATION_EXPERIMENT, "elo tournament",
                         params={"players": ", ".join(a.players), "deals": a.deals, "seed": a.seed},
                         metrics={f"elo.{n}": e for n, e in res.elo.items()}, tags={"kind": "elo"},
                         artifacts={"win_rates": {f"{x}>{y}": res.win_rate(x, y) for x in names for y in names if x != y}})


if __name__ == "__main__":
    asyncio.run(main())
