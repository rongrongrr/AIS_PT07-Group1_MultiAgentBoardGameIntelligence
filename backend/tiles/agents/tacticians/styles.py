"""Opponents whose habits the Profiler's model cannot describe exactly.

The Profiler models a player as seven weights on the seven parts of the move
score (``heuristics.py``). The opponents in the other experiments are all
built from those same seven parts, so the model can in principle represent
them exactly. The Tacticians here play like ``greedy`` but add a habit that
is not one of the seven parts: a favourite colour, a dislike of the centre,
a liking for the short pattern lines, or occasional random moves. They are
used to test whether the opponent model helps when the opponent only partly
fits it. They are looked up with ``make_style_tactician``; they are not
offered as playable Tacticians.
"""

from __future__ import annotations

import random
import time
from typing import Callable, Dict

from tiles.agents.base import (
    CandidateMove,
    Decision,
    DecisionContext,
    SearchReport,
    Tactician,
)
from tiles.core import Action, GameState

from .heuristics import DEFAULT_WEIGHTS, score_action


def _colour_loyal(state: GameState, action: Action) -> float:
    """Likes blue most and red second, whatever the move score says."""
    return {0: 4.0, 2: 2.0}.get(action.color, 0.0)


def _centre_averse(state: GameState, action: Action) -> float:
    """Dislikes taking from the centre."""
    return -4.0 if action.from_center else 0.0


def _low_rows(state: GameState, action: Action) -> float:
    """Likes the two shortest pattern lines and dislikes the longest two."""
    if action.to_floor:
        return 0.0
    return 3.0 if action.dest_row <= 1 else (-1.5 if action.dest_row >= 3 else 0.0)


#: Habit added to the greedy move score, by style name.
HABITS: Dict[str, Callable[[GameState, Action], float]] = {
    "colour_loyal": _colour_loyal,
    "centre_averse": _centre_averse,
    "low_rows": _low_rows,
}

#: Chance of a uniformly random move in the "noisy" style.
NOISE = 0.25


class StyleTactician(Tactician):
    """Greedy move score plus one habit (or occasional random moves)."""

    def __init__(self, style: str, seed: int = 0) -> None:
        if style != "noisy" and style not in HABITS:
            raise ValueError(f"unknown style {style!r}; available: {style_names()}")
        self.style = style
        self.name = f"style_{style}"
        self._rng = random.Random(seed)

    def decide(self, ctx: DecisionContext) -> Decision:
        start = time.perf_counter()
        if ctx.rng_seed is not None:
            self._rng.seed(ctx.rng_seed)
        scored = []
        for action in ctx.legal:
            base, components = score_action(ctx.state, action, DEFAULT_WEIGHTS)
            habit = HABITS[self.style](ctx.state, action) if self.style in HABITS else 0.0
            scored.append((base + habit, action, components))
        scored.sort(key=lambda item: item[0], reverse=True)
        chosen = scored[0]
        if self.style == "noisy" and self._rng.random() < NOISE:
            chosen = self._rng.choice(scored)
        candidates = [
            CandidateMove(action=a, score=s, notes=comp) for s, a, comp in [chosen] + [x for x in scored[:7] if x is not chosen]
        ]
        report = SearchReport(
            candidates=candidates,
            elapsed_ms=(time.perf_counter() - start) * 1000,
            notes={"strategy": f"greedy move score plus the {self.style} habit"},
        )
        return Decision(action=chosen[1], report=report)


def style_names() -> list:
    return sorted(list(HABITS) + ["noisy"])


def make_style_tactician(style: str, seed: int = 0) -> StyleTactician:
    return StyleTactician(style, seed=seed)
