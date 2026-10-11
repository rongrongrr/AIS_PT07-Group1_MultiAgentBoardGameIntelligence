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
from .heuristics import DEFAULT_WEIGHTS, endgame_weights, rank_actions, table_weights


class GreedyTactician(Tactician):
    name = "greedy"

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        table_aware: bool = False,
        endgame_aware: bool = False,
    ) -> None:
        # Partial weights override the defaults; missing keys keep them.
        self.weights = {**DEFAULT_WEIGHTS, **(weights or {})}
        # Set the first-player-token value from the number of players.
        self.table_aware = table_aware
        # Switch to closing-round weights once a wall row is one tile from complete.
        self.endgame_aware = endgame_aware

    def decide(self, ctx: DecisionContext) -> Decision:
        start = time.perf_counter()
        weights = (
            table_weights(self.weights, ctx.state.num_players)
            if self.table_aware
            else self.weights
        )
        if self.endgame_aware:
            weights = endgame_weights(weights, ctx.state)
        ranked = rank_actions(ctx.state, ctx.legal, weights)
        candidates = [
            CandidateMove(action=action, score=score, notes=components)
            for action, score, components in ranked[:8]
        ]
        report = SearchReport(
            candidates=candidates,
            elapsed_ms=(time.perf_counter() - start) * 1000,
            notes={
                "strategy": "weighted heuristic over legal actions",
                "weights": weights,
            },
        )
        return Decision(action=ranked[0][0], report=report)
