"""Seeded round-robin tournament between registered Machine Players.

Usage (from backend/):
    python scripts/tournament.py --games 200 --seed 1 --players GreedyPlayer RandomPlayer
    python scripts/tournament.py --games 100 --players GreedyPlayer RandomPlayer --out results.json

Every pairing is played from both seats on identical tile draws (same seed per
game pair), so seat/draw luck cancels. Win rate counts a draw as half a win and
is reported with a 95% Wilson interval.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.azul.game import play_game  # noqa: E402
from app.ml.greedy_player import GreedyPlayer  # noqa: E402
from app.ml.random_player import RandomPlayer  # noqa: E402
from app.ml.rollout_player import RolloutPlayer  # noqa: E402

PLAYERS = {"GreedyPlayer": GreedyPlayer, "RandomPlayer": RandomPlayer, "RolloutPlayer": RolloutPlayer}


def wilson(wins: float, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(centre - half, 3), round(centre + half, 3))


def make(name: str, seed: int):
    cls = PLAYERS[name]
    return cls(seed=seed) if name in ("RandomPlayer", "RolloutPlayer") else cls()


async def run_pair(a: str, b: str, games: int, seed: int) -> dict:
    wins = {a: 0.0, b: 0.0}
    scores = {a: [], b: []}
    for g in range(games):
        for order in ((a, b), (b, a)):
            players = [make(n, seed * 100003 + g) for n in order]
            names = [f"{n}#{i}" for i, n in enumerate(order)]
            res = await play_game(
                [p.decide for p in players], names, seed=seed * 100003 + g,
            )
            sc = {order[i]: res["scores"][names[i]] for i in range(2)}
            for n in order:
                scores[n].append(sc[n])
            if sc[a] > sc[b]:
                wins[a] += 1
            elif sc[b] > sc[a]:
                wins[b] += 1
            else:
                wins[a] += 0.5
                wins[b] += 0.5
    n = games * 2
    return {
        "pair": [a, b], "games": n,
        a: {"win_rate": round(wins[a] / n, 3), "ci95": wilson(wins[a], n),
            "mean_score": round(sum(scores[a]) / n, 1)},
        b: {"win_rate": round(wins[b] / n, 3), "ci95": wilson(wins[b], n),
            "mean_score": round(sum(scores[b]) / n, 1)},
    }


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=50, help="games per seat order per pairing")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--players", nargs="+", default=list(PLAYERS), choices=list(PLAYERS))
    ap.add_argument("--out", help="write JSON results here")
    args = ap.parse_args()

    results = []
    for a, b in itertools.combinations(args.players, 2):
        r = await run_pair(a, b, args.games, args.seed)
        results.append(r)
        print(f"{a} vs {b} ({r['games']} games): "
              f"{a} {r[a]['win_rate']:.1%} {r[a]['ci95']} avg {r[a]['mean_score']} | "
              f"{b} {r[b]['win_rate']:.1%} {r[b]['ci95']} avg {r[b]['mean_score']}")
    if args.out:
        Path(args.out).write_text(json.dumps({"seed": args.seed, "results": results}, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
