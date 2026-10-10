"""Template-based Explainer.

Maps decision artifacts (heuristic component breakdowns, MCTS visit
statistics, principal variations, profiler archetypes) onto natural
language via deterministic templates — no LLM in the loop, so every
explanation is reproducible and auditable.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from tiles.agents.base import (
    CandidateMove,
    Decision,
    DecisionContext,
    Explainer,
    Explanation,
)
from tiles.agents.tacticians.heuristics import DEFAULT_WEIGHTS
from tiles.core import Action, GameState, MoveResult

# Phrases for the heuristic component that dominated the decision.
_DRIVER_PHRASES: Dict[str, str] = {
    "immediate_points": "completes a pattern line for {points:.0f} immediate point{plural}",
    "denial": "denies tiles an opponent visibly needs",
    "bonus_potential": "builds toward a row, column or color bonus",
    "floor_penalty": "accepts a floor penalty as the least bad option",
    "first_player": "takes the first-player token to lead the next round",
    "line_progress": "develops a pattern line toward completion",
    "near_completion": "brings a pattern line close to completion",
}


def _weighted_components(notes: Dict[str, float]) -> Dict[str, float]:
    return {
        key: DEFAULT_WEIGHTS.get(key, 1.0) * value
        for key, value in notes.items()
        if isinstance(value, (int, float)) and key in _DRIVER_PHRASES
    }


def _primary_driver(notes: Dict[str, float]) -> Optional[str]:
    weighted = _weighted_components(notes)
    if not weighted:
        return None
    key = max(weighted, key=lambda k: weighted[k])
    if weighted[key] <= 0:
        # Everything is zero or negative: the move is damage control.
        return "floor_penalty" if notes.get("floor_penalty", 0) < 0 else None
    return key


def _driver_sentence(key: str, notes: Dict[str, float]) -> str:
    phrase = _DRIVER_PHRASES[key]
    points = notes.get("immediate_points", 0.0)
    return phrase.format(points=points, plural="" if points == 1 else "s")


def _margin_phrase(best: CandidateMove, runner: Optional[CandidateMove]) -> str:
    if runner is None:
        return "it was the standout option"
    if best.visits > 0 and runner.visits > 0:
        ratio = best.visits / max(runner.visits, 1)
        if ratio >= 1.5:
            return "it was clearly the best option in search"
        return f"narrowly preferred over the alternative to {runner.action.describe()}"
    gap = best.score - runner.score
    scale = max(abs(best.score), abs(runner.score), 1.0)
    if gap / scale >= 0.25:
        return "it was clearly the best option"
    return f"narrowly preferred over the alternative to {runner.action.describe()}"


def _pv_phrase(best: CandidateMove, simulations: int) -> str:
    parts = []
    if simulations > 0:
        parts.append(f"after {simulations} simulations")
    if best.principal_variation:
        continuation = " then ".join(
            a.describe() for a in best.principal_variation[:3]
        )
        parts.append(f"expected continuation: {continuation}")
    return "; ".join(parts)


def _endgame_near(state: GameState) -> bool:
    for board in state.players:
        for r in range(5):
            if sum(1 for c in range(5) if board.wall_has(r, c)) >= 4:
                return True
    return False


def _concepts(
    ctx: DecisionContext,
    action: Action,
    notes: Dict[str, float],
    move: Optional[MoveResult],
) -> List[str]:
    concepts: List[str] = []
    completed = move.completed_line if move else notes.get("immediate_points", 0) > 0
    if completed:
        concepts.append("COMPLETES_LINE")
    if notes.get("denial", 0) > 1.0:
        concepts.append("BLOCKS_OPPONENT")
    if notes.get("bonus_potential", 0) > 0:
        concepts.append("BONUS_SETUP")
    floored = move.tiles_to_floor > 0 if move else action.to_floor
    if floored or action.to_floor:
        concepts.append("FLOOR_SACRIFICE")
    took_fpt = (
        move.took_first_player_token
        if move
        else (action.from_center and ctx.state.center_has_fpt)
    )
    if took_fpt:
        concepts.append("TAKES_FIRST_PLAYER")
    if len(ctx.legal) == 1:
        concepts.append("FORCED")
    if _endgame_near(ctx.state):
        concepts.append("ENDGAME")
    return concepts


class TemplateExplainer(Explainer):
    name = "template"

    def explain(
        self,
        ctx: DecisionContext,
        decision: Decision,
        move: Optional[MoveResult] = None,
    ) -> Explanation:
        action = decision.action
        player = ctx.state.players[ctx.player_index].name
        report = decision.report
        notes: Dict[str, float] = {}
        if report and report.best is not None:
            notes = {
                k: v
                for k, v in report.best.notes.items()
                if isinstance(v, (int, float))
            }
        concepts = _concepts(ctx, action, notes, move)

        if "FORCED" in concepts:
            return Explanation(
                text=f"{player} had no choice: {action.describe()} was the only legal move.",
                concepts=concepts,
                evidence={"legal_actions": 1},
            )

        if report is None or report.best is None:
            return Explanation(
                text=f"{player} chose to {action.describe()}.",
                concepts=concepts,
                evidence={},
            )

        best = report.best
        runner = report.runner_up
        driver = _primary_driver(notes)

        sentences: List[str] = []
        if driver is not None:
            sentences.append(
                f"{player} chose to {action.describe()}: it "
                f"{_driver_sentence(driver, notes)}."
            )
        else:
            sentences.append(f"{player} chose to {action.describe()}.")

        margin = _margin_phrase(best, runner)
        pv = _pv_phrase(best, report.simulations)
        second = margin[0].upper() + margin[1:]
        if pv:
            second += f" ({pv})"
        sentences.append(second + ".")

        if report.used_opponent_model and ctx.profiles:
            for idx, profile in sorted(ctx.profiles.items()):
                if idx != ctx.player_index and profile.moves_observed > 0:
                    sentences.append(
                        f"The search was biased by the Profiler, expecting "
                        f"{profile.player_name} ({profile.archetype}, "
                        f"{profile.moves_observed} moves observed) to "
                        f"contest the shared supply."
                    )
                    break

        evidence: Dict[str, object] = {
            "primary_driver": driver,
            "components": {k: round(v, 3) for k, v in notes.items()},
            "simulations": report.simulations,
            "used_opponent_model": report.used_opponent_model,
        }
        if runner is not None:
            evidence["score_gap"] = round(best.score - runner.score, 3)
            evidence["runner_up"] = runner.action.describe()
        if best.principal_variation:
            evidence["principal_variation"] = [
                str(a) for a in best.principal_variation[:5]
            ]

        return Explanation(
            text=" ".join(sentences), concepts=concepts, evidence=evidence
        )
