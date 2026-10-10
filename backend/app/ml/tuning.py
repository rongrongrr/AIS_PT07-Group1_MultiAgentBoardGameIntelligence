"""Genetic-algorithm tuning of the heuristic move-scoring weights.

A genome is the vector of ``Weights`` fields. Fitness is the mean score margin (plus a win bonus)
of a GreedyPlayer using those weights against a fixed reference pool, on deals shared by every
candidate in a generation (common random numbers), so differences between genomes come from the
weights and not from luck. Selection is by tournament, crossover is a random blend, mutation is
Gaussian and clipped to per-gene bounds. The best genome is re-evaluated on unseen deals by
scripts/tune_weights.py before being trusted.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, fields
from typing import Callable, Dict, List, Sequence, Tuple

from app.azul.game import play_game
from app.ml.greedy_player import DEFAULT_WEIGHTS, GreedyPlayer, Weights

BOUNDS: Dict[str, Tuple[float, float]] = {
    "wall": (0.5, 6.0), "fill": (0.0, 5.0), "row_pref": (0.0, 3.0), "bonus": (0.0, 5.0),
    "overflow": (0.0, 2.5), "floor": (0.1, 2.5), "block": (0.0, 6.0), "loyalty": (0.0, 3.0), "volume": (0.0, 2.0),
}
GENES = [f.name for f in fields(Weights)]


def to_weights(genome: Sequence[float]) -> Weights:
    return Weights(**{g: float(v) for g, v in zip(GENES, genome)})


def to_genome(w: Weights) -> List[float]:
    return [getattr(w, g) for g in GENES]


def clip(genome: Sequence[float]) -> List[float]:
    return [min(max(v, BOUNDS[g][0]), BOUNDS[g][1]) for g, v in zip(GENES, genome)]


async def evaluate(weights: Weights, opponents: Sequence[Callable[[], object]], deals: Sequence[int]) -> float:
    """Mean margin over the reference pool, from both seats, plus 10 per win."""
    total, n = 0.0, 0
    for opp_make in opponents:
        for d in deals:
            for first in (True, False):
                me, opp = GreedyPlayer(weights=weights), opp_make()
                ps = [me, opp] if first else [opp, me]
                names = ["ME", "OPP"] if first else ["OPP", "ME"]
                r = await play_game([p.decide for p in ps], names, seed=d)
                diff = r["scores"]["ME"] - r["scores"]["OPP"]
                total += diff + (10 if diff > 0 else 0)
                n += 1
    return total / n


@dataclass
class GAResult:
    best: Weights
    best_fitness: float
    history: List[Dict[str, float]]


async def evolve(opponents: Sequence[Callable[[], object]], population: int = 16, generations: int = 8,
                 deals_per_eval: int = 4, seed: int = 0, mutation: float = 0.25, elite: int = 2,
                 on_generation: Callable[[int, float, float], None] = None) -> GAResult:
    rng = random.Random(seed)
    pop = [to_genome(DEFAULT_WEIGHTS)] + [
        clip([v * rng.uniform(0.5, 1.6) + rng.gauss(0, 0.2) for v in to_genome(DEFAULT_WEIGHTS)])
        for _ in range(population - 1)
    ]
    history: List[Dict[str, float]] = []
    best_g, best_f = pop[0], float("-inf")
    for gen in range(generations):
        deals = [seed * 10_000 + gen * 100 + i for i in range(deals_per_eval)]       # new deals each generation
        fits = [await evaluate(to_weights(g), opponents, deals) for g in pop]
        ranked = sorted(zip(fits, pop), key=lambda x: x[0], reverse=True)
        if ranked[0][0] > best_f:
            best_f, best_g = ranked[0]
        history.append({"generation": gen, "best": ranked[0][0], "mean": sum(fits) / len(fits)})
        if on_generation:
            on_generation(gen, ranked[0][0], sum(fits) / len(fits))
        nxt = [g for _, g in ranked[:elite]]
        while len(nxt) < population:
            a = max(rng.sample(ranked, 3), key=lambda x: x[0])[1]
            b = max(rng.sample(ranked, 3), key=lambda x: x[0])[1]
            child = [rng.choice((x, y)) if rng.random() < 0.5 else x * (t := rng.random()) + y * (1 - t)
                     for x, y in zip(a, b)]
            child = [v + rng.gauss(0, mutation * (BOUNDS[g][1] - BOUNDS[g][0]) * 0.2) if rng.random() < 0.35 else v
                     for g, v in zip(GENES, child)]
            nxt.append(clip(child))
        pop = nxt
    return GAResult(to_weights(best_g), best_f, history)
