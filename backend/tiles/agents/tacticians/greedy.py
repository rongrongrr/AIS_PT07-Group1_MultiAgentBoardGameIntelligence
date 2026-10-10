"""Greedy heuristic Tactician.

Scores every legal action with the shared weighted heuristic and picks
the best. The per-component breakdown is preserved in the SearchReport
so the Explainer can say *why* the move won.
"""

from __future__ import annotations

import time
from typing import Dict, Optional

from tiles.agents.base import (
    CandidateMove,
    Decision,
    DecisionContext,
    SearchReport,
    Tactician,
)
from .heuristics import DEFAULT_WEIGHTS, rank_actions


class GreedyTactician(Tactician):
    name = "greedy"

    def __init__(self, weights: Optional[Dict[str, float]] = None) -> None:
        # Partial weights override the defaults; missing keys keep them.
        self.weights = {**DEFAULT_WEIGHTS, **(weights or {})}

    def decide(self, ctx: DecisionContext) -> Decision:
        start = time.perf_counter()
        ranked = rank_actions(ctx.state, ctx.legal, self.weights)
        candidates = [
            CandidateMove(action=action, score=score, notes=components)
            for action, score, components in ranked[:8]
        ]
        report = SearchReport(
            candidates=candidates,
            elapsed_ms=(time.perf_counter() - start) * 1000,
            notes={
                "strategy": "weighted heuristic over legal actions",
                "weights": self.weights,
            },
        )
        return Decision(action=ranked[0][0], report=report)
