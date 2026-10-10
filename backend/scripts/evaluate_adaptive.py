"""Does adapting to the opponent's inferred archetype beat the static baseline?

    python scripts/evaluate_adaptive.py --games 100 --seed 99

For each opponent archetype: AdaptivePlayer vs opponent, and GreedyPlayer vs the same
opponent on the same deals. Reports win rates with 95% CIs. Run on seeds not used for
training (train_archetypes.py) or best-response selection (best_response.py).
"""

from __future__ import annotations

import argparse
import asyncio

from duel import duel

from tiles.ml.adaptive_player import AdaptivePlayer
from tiles.ml.greedy_player import (
    BlockerPlayer, ColorCollectorPlayer, GreedyPlayer, RecklessPlayer, RusherPlayer,
)

OPPONENTS = [GreedyPlayer, ColorCollectorPlayer, RusherPlayer, RecklessPlayer, BlockerPlayer]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--seed", type=int, default=99)
    args = ap.parse_args()

    print(f"{'opponent':<22} {'Adaptive win rate (95% CI)':<30} {'Greedy win rate (95% CI)':<30} diff")
    tot_a = tot_g = 0.0
    for opp in OPPONENTS:
        a = await duel(AdaptivePlayer, opp, args.games, args.seed)
        g = await duel(GreedyPlayer, opp, args.games, args.seed)
        tot_a += a["win_rate"]
        tot_g += g["win_rate"]
        print(f"{opp.__name__:<22} {a['win_rate']:.3f} {str(a['ci95']):<22} "
              f"{g['win_rate']:.3f} {str(g['ci95']):<22} {a['win_rate'] - g['win_rate']:+.3f}")
    n = len(OPPONENTS)
    print(f"{'MEAN':<22} {tot_a / n:.3f} {'':<22} {tot_g / n:.3f} {'':<22} {(tot_a - tot_g) / n:+.3f}")


if __name__ == "__main__":
    asyncio.run(main())
