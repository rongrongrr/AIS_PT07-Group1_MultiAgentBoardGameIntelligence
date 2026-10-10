"""Strength of MCTS and the effect of profiler conditioning.

    python scripts/evaluate_mcts.py --games 8 --seed 41

Part 1: MCTSPlayer against Greedy, Minimax and Rollout players (win rate, 95% CI, mean scores).
Part 2: for each opponent style, ConditionedMCTSPlayer vs MCTSPlayer, each facing that style on the
        same deals; reports win rate and mean score margin against the style.
"""

from __future__ import annotations

import argparse
import asyncio
import time

from duel import duel

from tiles.azul.game import play_game
from tiles.ml.greedy_player import (
    BlockerPlayer, ColorCollectorPlayer, GreedyPlayer, RecklessPlayer, RusherPlayer,
)
from tiles.ml.mcts_player import ConditionedMCTSPlayer, MCTSPlayer
from tiles.ml.minimax_player import MinimaxPlayer
from tiles.ml.rollout_player import RolloutPlayer

STYLES = [GreedyPlayer, ColorCollectorPlayer, RusherPlayer, RecklessPlayer, BlockerPlayer]


async def margin_vs(make_me, make_opp, games: int, seed: int):
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
    return wins / len(diffs), sum(diffs) / len(diffs)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=8)
    ap.add_argument("--seed", type=int, default=41)
    a = ap.parse_args()

    print("Part 1: MCTSPlayer vs other players")
    for name, make in (("GreedyPlayer", GreedyPlayer), ("MinimaxPlayer", MinimaxPlayer),
                       ("RolloutPlayer", lambda: RolloutPlayer(seed=3))):
        t = time.time()
        r = await duel(lambda: MCTSPlayer(seed=1), make, a.games, a.seed)
        print(f"  vs {name:<14} win {r['win_rate']:.2f} {r['ci95']} margin {r['mean_score_diff']:+.1f} "
              f"({r['games']} games, {time.time() - t:.0f}s)", flush=True)

    print("\nPart 2: profiler conditioning (margin against each opponent style)")
    print(f"{'opponent style':<22} {'Conditioned win / margin':<28} {'Plain MCTS win / margin':<28} margin gain")
    tot = 0.0
    for opp in STYLES:
        cw, cm = await margin_vs(lambda: ConditionedMCTSPlayer(seed=2), opp, a.games, a.seed)
        pw, pm = await margin_vs(lambda: MCTSPlayer(seed=2), opp, a.games, a.seed)
        tot += cm - pm
        print(f"{opp.__name__:<22} {cw:.2f} / {cm:+6.1f}{'':<14} {pw:.2f} / {pm:+6.1f}{'':<12} {cm - pm:+.1f}", flush=True)
    print(f"{'MEAN margin gain':<22} {tot / len(STYLES):+.1f}")


if __name__ == "__main__":
    asyncio.run(main())
