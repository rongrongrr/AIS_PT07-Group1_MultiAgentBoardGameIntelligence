"""Depth-limited Minimax Tactician (paranoid reduction for 3-4 players).

Search stays within the current round: drafting is deterministic between
redeals, so the tree is exact until an action resolves the round. A
round-resolving child is evaluated immediately after resolution (never
searched past the stochastic redeal).

Values are always from the ROOT player's perspective. The root player
maximizes; every other player minimizes (the "paranoid" reduction, which
is exact for 2 players and pessimistic-but-sound for 3-4). This makes
plain alpha-beta pruning valid for any player count.

For tractability in pure Python, non-root nodes consider only the top
``beam_width`` heuristically-ranked moves (the root considers all).
Root sibling values are searched with a running alpha window, so
runner-up scores are fail-soft bounds — fine for candidate ordering.
"""

from __future__ import annotations

import time
from typing import List, Tuple

from tiles.agents.base import (
    CandidateMove,
    Decision,
    DecisionContext,
    SearchReport,
    Tactician,
)
from tiles.core import Action, GameState, legal_actions, step

from .heuristics import evaluate_state, rank_actions

_INF = float("inf")
_WIN_BONUS = 100.0


class MinimaxTactician(Tactician):
    name = "minimax"

    def __init__(self, depth: int = 3, beam_width: int = 12) -> None:
        self.depth = depth
        self.beam_width = beam_width

    # -- evaluation -----------------------------------------------------------

    @staticmethod
    def _terminal_value(state: GameState, root: int) -> float:
        scores = state.scores()
        mine = scores[root]
        best_other = max(s for i, s in enumerate(scores) if i != root)
        margin = float(mine - best_other)
        if margin > 0:
            return _WIN_BONUS + margin
        if margin < 0:
            return -_WIN_BONUS + margin
        return 0.0

    def _leaf_value(self, state: GameState, root: int) -> float:
        if state.is_game_over:
            return self._terminal_value(state, root)
        return evaluate_state(state, root)

    # -- search ---------------------------------------------------------------

    def _search(
        self,
        state: GameState,
        depth: int,
        alpha: float,
        beta: float,
        root: int,
    ) -> Tuple[float, List[Action]]:
        if state.is_game_over:
            return self._terminal_value(state, root), []
        if depth == 0:
            return evaluate_state(state, root), []

        legal = legal_actions(state)
        ranked = rank_actions(state, legal)[: self.beam_width]
        is_max = state.current_player == root

        best_value = -_INF if is_max else _INF
        best_pv: List[Action] = []
        for action, _, _ in ranked:
            child = state.clone()
            _, round_result = step(child, action)
            if round_result is not None:
                # Round resolved: evaluate here, never search past the redeal.
                value, pv = self._leaf_value(child, root), []
            else:
                value, pv = self._search(child, depth - 1, alpha, beta, root)
            if is_max:
                if value > best_value:
                    best_value, best_pv = value, [action] + pv
                alpha = max(alpha, best_value)
            else:
                if value < best_value:
                    best_value, best_pv = value, [action] + pv
                beta = min(beta, best_value)
            if beta <= alpha:
                break
        return best_value, best_pv

    # -- Tactician interface --------------------------------------------------

    def decide(self, ctx: DecisionContext) -> Decision:
        start = time.perf_counter()
        root = ctx.player_index
        state = ctx.state

        candidates: List[CandidateMove] = []
        alpha = -_INF
        for action, heuristic, components in rank_actions(state, ctx.legal):
            child = state.clone()
            _, round_result = step(child, action)
            if round_result is not None:
                value, pv = self._leaf_value(child, root), []
            else:
                value, pv = self._search(
                    child, self.depth - 1, alpha, _INF, root
                )
            alpha = max(alpha, value)
            candidates.append(
                CandidateMove(
                    action=action,
                    score=value,
                    principal_variation=[action] + pv,
                    notes={"heuristic": heuristic, **components},
                )
            )

        candidates.sort(key=lambda c: c.score, reverse=True)
        report = SearchReport(
            candidates=candidates[:8],
            simulations=0,
            elapsed_ms=(time.perf_counter() - start) * 1000,
            notes={
                "strategy": f"paranoid minimax, depth {self.depth}, "
                f"beam {self.beam_width}",
                "depth": self.depth,
            },
        )
        return Decision(action=candidates[0].action, report=report)
