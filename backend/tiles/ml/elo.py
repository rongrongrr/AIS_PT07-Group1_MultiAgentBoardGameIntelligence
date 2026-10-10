"""Elo ratings and round-robin tournaments over simulated games."""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Tuple

from tiles.azul.game import play_game


@dataclass
class EloRatings:
    k: float = 24.0
    base: float = 1500.0
    ratings: Dict[str, float] = field(default_factory=dict)

    def get(self, name: str) -> float:
        return self.ratings.setdefault(name, self.base)

    @staticmethod
    def expected(ra: float, rb: float) -> float:
        return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))

    def update(self, a: str, b: str, score_a: float) -> None:
        """score_a: 1 win, 0.5 draw, 0 loss for a."""
        ra, rb = self.get(a), self.get(b)
        ea = self.expected(ra, rb)
        self.ratings[a] = ra + self.k * (score_a - ea)
        self.ratings[b] = rb + self.k * ((1 - score_a) - (1 - ea))


@dataclass
class TournamentResult:
    elo: Dict[str, float]
    wins: Dict[Tuple[str, str], float]          # (row, col) -> points won by row against col
    games: Dict[Tuple[str, str], int]
    mean_score: Dict[str, float]
    n_games: int

    def win_rate(self, a: str, b: str) -> float:
        g = self.games.get((a, b), 0)
        return self.wins.get((a, b), 0.0) / g if g else float("nan")

    def ranking(self) -> List[Tuple[str, float]]:
        return sorted(self.elo.items(), key=lambda kv: kv[1], reverse=True)


async def round_robin(players: Dict[str, Callable[[int], object]], deals: int, seed: int = 0,
                      elo_passes: int = 20) -> TournamentResult:
    """Every pair plays ``deals`` deals from both seats. ``players`` maps name -> factory(seed).

    Elo is computed from the full set of results by replaying them in random order several times
    and averaging, which removes most of the order dependence of online Elo.
    """
    names = list(players)
    results: List[Tuple[str, str, float]] = []
    wins: Dict[Tuple[str, str], float] = {}
    games: Dict[Tuple[str, str], int] = {}
    scores: Dict[str, List[int]] = {n: [] for n in names}
    for a, b in itertools.combinations(names, 2):
        for d in range(deals):
            deal_seed = seed * 1_000_003 + d
            for a_first in (True, False):
                pa, pb = players[a](deal_seed), players[b](deal_seed + 7)
                order = [pa, pb] if a_first else [pb, pa]
                tags = ["A", "B"] if a_first else ["B", "A"]
                res = await play_game([p.decide for p in order], tags, seed=deal_seed,
                                      observers=[getattr(p, "observe", None) for p in order])
                sa, sb = res["scores"]["A"], res["scores"]["B"]
                sc = 1.0 if sa > sb else 0.5 if sa == sb else 0.0
                results.append((a, b, sc))
                scores[a].append(sa)
                scores[b].append(sb)
                for x, y, pts in ((a, b, sc), (b, a, 1 - sc)):
                    wins[(x, y)] = wins.get((x, y), 0.0) + pts
                    games[(x, y)] = games.get((x, y), 0) + 1
    rng = random.Random(seed)
    total = {n: 0.0 for n in names}
    for _ in range(elo_passes):
        elo = EloRatings()
        order = results[:]
        rng.shuffle(order)
        for a, b, sc in order:
            elo.update(a, b, sc)
        for n in names:
            total[n] += elo.get(n)
    mean_elo = {n: total[n] / elo_passes for n in names}
    return TournamentResult(
        elo=mean_elo, wins=wins, games=games,
        mean_score={n: (sum(v) / len(v) if v else 0.0) for n, v in scores.items()}, n_games=len(results))
