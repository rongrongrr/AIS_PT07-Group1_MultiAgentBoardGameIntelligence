"""LLM-refined Explainer.

Wraps :class:`TemplateExplainer` and, when an Anthropic API key is
available, asks Claude to rewrite the deterministic template rationale
as livelier two-sentence commentary. Every factual input (chosen move,
candidate table, board context) comes from the template layer, so the
LLM adds style, not facts. Any failure — missing key, missing package,
network error — falls back silently to the template text.
"""

from __future__ import annotations

import os
from typing import Optional

from tiles.agents.base import Decision, DecisionContext, Explainer, Explanation
from tiles.core import COLOR_NAMES, MoveResult

from .templates import TemplateExplainer

_MODEL = "claude-opus-5-5"

_SYSTEM = (
    "You are the color commentator for TILES, an AI system that plays the "
    "board game Azul. Rewrite the provided draft rationale as exactly two "
    "vivid, concrete sentences of live commentary. Preserve every fact "
    "(player, tiles, destinations, point counts); never invent moves or "
    "numbers that are not in the draft or the candidate table."
)


class LLMExplainer(Explainer):
    name = "llm"

    def __init__(self) -> None:
        self._template = TemplateExplainer()

    # -- helpers --------------------------------------------------------------

    @staticmethod
    def _board_context(ctx: DecisionContext) -> str:
        state = ctx.state
        lines = [f"Round {state.round_number}."]
        for board in state.players:
            lines.append(f"{board.name}: {board.score} points.")
        center = ", ".join(
            f"{n} {COLOR_NAMES[c]}" for c, n in enumerate(state.center) if n
        )
        if center:
            lines.append(f"Center pool: {center}.")
        return " ".join(lines)

    @staticmethod
    def _candidate_table(decision: Decision) -> str:
        if not decision.report or not decision.report.candidates:
            return ""
        rows = []
        for cand in decision.report.candidates[:4]:
            rows.append(
                f"- {cand.action.describe()} (score {cand.score:.2f}"
                + (f", visits {cand.visits}" if cand.visits else "")
                + ")"
            )
        return "Candidates considered:\n" + "\n".join(rows)

    def _rewrite(self, prompt: str) -> Optional[str]:
        import anthropic  # lazy: optional dependency

        client = anthropic.Anthropic()
        for _ in range(2):  # one retry, then give up
            try:
                response = client.messages.create(
                    model=_MODEL,
                    max_tokens=1000,
                    system=_SYSTEM,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = "".join(
                    block.text
                    for block in response.content
                    if block.type == "text"
                ).strip()
                if text:
                    return text
            except Exception:  # noqa: BLE001 — never break a game turn
                continue
        return None

    # -- Explainer ------------------------------------------------------------

    def explain(
        self,
        ctx: DecisionContext,
        decision: Decision,
        move: Optional[MoveResult] = None,
    ) -> Explanation:
        base = self._template.explain(ctx, decision, move)
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return base
        try:
            prompt = (
                f"Board context: {self._board_context(ctx)}\n\n"
                f"Draft rationale: {base.text}\n\n"
                f"{self._candidate_table(decision)}"
            )
            rewritten = self._rewrite(prompt)
        except Exception:  # noqa: BLE001 — includes ImportError
            rewritten = None
        if not rewritten:
            return base
        return Explanation(
            text=rewritten,
            concepts=base.concepts,
            evidence={**base.evidence, "template_text": base.text},
        )
