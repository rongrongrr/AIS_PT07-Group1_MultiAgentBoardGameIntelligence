"""Strength of the lookahead players, and whether opponent modelling helps inside the search.

    python scripts/evaluate_lookahead.py --games 15 --seed 55

Part 1: RolloutPlayer vs GreedyPlayer (win rate, 95% CI, score margin).
Part 2: for each opponent style, AdaptiveRolloutPlayer vs RolloutPlayer, each facing that style
        on the same deals; reports win rate and mean score margin against the opponent.
"""

from __future__ import annotations

import argparse
import asyncio
import time

from duel import duel

from tiles.azul.game import play_game
from tiles.ml.adaptive_player import AdaptiveRolloutPlayer
from tiles.ml.greedy_player import (
    BlockerPlayer, ColorCollectorPlayer, GreedyPlayer, RecklessPlayer, RusherPlayer,
)
from tiles.ml.rollout_player import RolloutPlayer

OPPONENTS = [GreedyPlayer, ColorCollectorPlayer, RusherPlayer, RecklessPlayer, BlockerPlayer]


async def margin_vs(make_me, make_opp, games: int, seed: int):
    """Mean (my score - opponent score) and my win rate, both seats, shared deals."""
    diffs, wins = [], 0.0
    for g in range(games):
        deal = seed * 1_000_003 + g
        for me_first in (True, False):
            me, opp = make_me(), make_opp()
            ps = [me, opp] if me_first else [opp, me]
            names = ["ME", "OPP"] if me_first else ["OPP", "ME"]
            r = await play_game([p.decide for p in ps], names, seed=deal,
                                observers=[getattr(p, "observe", None) for p in ps])
            d = r["scores"]["ME"] - r["scores"]["OPP"]
            diffs.append(d)
            wins += 1.0 if d > 0 else 0.5 if d == 0 else 0.0
    n = len(diffs)
    return wins / n, sum(diffs) / n


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=15)
    ap.add_argument("--seed", type=int, default=55)
    a = ap.parse_args()

    t = time.time()
    r = await duel(lambda: RolloutPlayer(seed=1), GreedyPlayer, a.games, a.seed)
    print(f"RolloutPlayer vs GreedyPlayer: win {r['win_rate']:.2f} {r['ci95']} margin {r['mean_score_diff']:+.1f} "
          f"({r['games']} games, {time.time() - t:.0f}s)\n", flush=True)

    print(f"{'opponent style':<22} {'AdaptiveRollout win / margin':<32} {'Rollout win / margin':<28} margin gain")
    tot = 0.0
    for opp in OPPONENTS:
        aw, am = await margin_vs(lambda: AdaptiveRolloutPlayer(seed=2), opp, a.games, a.seed)
        rw, rm = await margin_vs(lambda: RolloutPlayer(seed=2), opp, a.games, a.seed)
        tot += am - rm
        print(f"{opp.__name__:<22} {aw:.2f} / {am:+6.1f}{'':<18} {rw:.2f} / {rm:+6.1f}{'':<12} {am - rm:+.1f}", flush=True)
    print(f"{'MEAN margin gain':<22} {tot / len(OPPONENTS):+.1f}")


if __name__ == "__main__":
    asyncio.run(main())
