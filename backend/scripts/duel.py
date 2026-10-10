"""Shared head-to-head runner for the evaluation scripts."""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tiles.azul.game import play_game  # noqa: E402


def wilson(wins: float, n: int, z: float = 1.96):
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(centre - half, 3), round(centre + half, 3))


async def duel(make_a: Callable[[], object], make_b: Callable[[], object], games: int, seed: int) -> dict:
    """Play ``games`` deals from both seats (2 x games results). Fresh players per game.

    Returns A's win rate (draw = half), 95% Wilson CI, and mean score difference.
    """
    wins = 0.0
    diffs = []
    for g in range(games):
        deal_seed = seed * 1_000_003 + g
        for a_first in (True, False):
            a, b = make_a(), make_b()
            players = [a, b] if a_first else [b, a]
            names = ["A", "B"] if a_first else ["B", "A"]
            res = await play_game(
                [p.decide for p in players], names, seed=deal_seed,
                observers=[getattr(p, "observe", None) for p in players],
            )
            diff = res["scores"]["A"] - res["scores"]["B"]
            diffs.append(diff)
            wins += 1.0 if diff > 0 else 0.5 if diff == 0 else 0.0
    n = games * 2
    return {"games": n, "win_rate": round(wins / n, 3), "ci95": wilson(wins, n),
            "mean_score_diff": round(sum(diffs) / n, 1)}
