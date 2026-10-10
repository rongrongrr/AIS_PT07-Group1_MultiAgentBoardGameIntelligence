"""Uniform-random baseline Tactician."""

from __future__ import annotations

import random
import time

from tiles.agents.base import (
    CandidateMove,
    Decision,
    DecisionContext,
    SearchReport,
    Tactician,
)


class RandomTactician(Tactician):
    name = "random"

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    def decide(self, ctx: DecisionContext) -> Decision:
        start = time.perf_counter()
        if ctx.rng_seed is not None:
            self._rng.seed(ctx.rng_seed)
        action = self._rng.choice(ctx.legal)
        report = SearchReport(
            candidates=[CandidateMove(action=action, score=0.0)],
            elapsed_ms=(time.perf_counter() - start) * 1000,
            notes={"strategy": "uniform random over legal actions"},
        )
        return Decision(action=action, report=report)
