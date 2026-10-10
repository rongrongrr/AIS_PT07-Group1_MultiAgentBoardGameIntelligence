"""Learn, by simulation, which play-style is the best response to each opponent archetype.

    python scripts/best_response.py --games 80 --seed 21

Every candidate style plays every opponent archetype from both seats on shared deals.
Output: models/best_response.json (used by AdaptivePlayer). Use a different --seed
from the one used in scripts/evaluate_adaptive.py so evaluation is on unseen deals.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from duel import duel

from app.ml.adaptive_player import BEST_RESPONSE_PATH
from app.ml.greedy_player import (
    COUNTER_STYLES, BlockerPlayer, ColorCollectorPlayer, GreedyPlayer, RecklessPlayer, RusherPlayer,
)

OPPONENTS = {c.__name__: c for c in (GreedyPlayer, ColorCollectorPlayer, RusherPlayer, RecklessPlayer, BlockerPlayer)}


def candidate(weights):
    return lambda: GreedyPlayer(weights=weights)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=80, help="deals per (candidate, opponent); played from both seats")
    ap.add_argument("--seed", type=int, default=21)
    args = ap.parse_args()

    responses = {}
    for opp_name, opp_cls in OPPONENTS.items():
        table = {}
        for cand_name, w in COUNTER_STYLES.items():
            r = await duel(candidate(w), opp_cls, args.games, args.seed)
            table[cand_name] = r
        best = max(table, key=lambda c: (table[c]["win_rate"], table[c]["mean_score_diff"]))
        responses[opp_name] = {"best": best, "table": table}
        row = "  ".join(f"{c[:12]}={table[c]['win_rate']:.2f}" for c in table)
        print(f"vs {opp_name:<22} best={best:<22} {row}")

    BEST_RESPONSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BEST_RESPONSE_PATH.write_text(json.dumps(
        {"games_per_cell": args.games * 2, "seed": args.seed, "responses": responses}, indent=2))
    print(f"saved -> {BEST_RESPONSE_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
