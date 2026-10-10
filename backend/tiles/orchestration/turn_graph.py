"""Validator-coordinated turn pipeline.

This is the runnable expression of the report's LangGraph design: a
deterministic graph whose nodes mutate a shared per-turn state, with the
Validator gating every state transition. Node -> report mapping:

    sense    -> "sensing the state"        (snapshot + legal actions)
    profile  -> "profiling the opponent"   (Profiler outputs injected)
    decide   -> "searching for moves"      (Tactician proposal)
    validate -> "validating the move"      (Validator gate; reject edge
                 routes back to `decide` once, then to a greedy fallback)
    execute  -> state transition            (tiles.core.step)
    observe  -> Profiler ingests the move
    explain  -> "explaining the choice"    (Explainer rationale)

The graph is framework-free on purpose (no LLM decides routing — edges
are explicit Python control flow), which is exactly the property the
report selects LangGraph for; swapping this class for a
``langgraph.StateGraph`` is a mechanical translation of the same nodes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from tiles.agents.base import (
    Decision,
    DecisionContext,
    Explainer,
    Profiler,
    Tactician,
)
from tiles.agents.tacticians.heuristics import rank_actions
from tiles.agents.validator import Validator
from tiles.core import (
    GameState,
    MoveResult,
    RoundResult,
    step,
)


def round_result_to_dict(result: RoundResult) -> dict:
    from tiles.core import COLOR_NAMES

    return {
        "round": result.round_number,
        "tilings": [
            {
                "player_index": t.player_index,
                "row": t.row,
                "col": t.col,
                "color": COLOR_NAMES[t.color],
                "points": t.points,
            }
            for t in result.tilings
        ],
        "floor_penalties": result.floor_penalties,
        "scores": result.scores,
        "game_over": result.game_over,
        "bonuses": result.bonuses,
    }


@dataclass
class TurnPipeline:
    """Runs one full turn through the Decision Stack."""

    validator: Validator
    tacticians: Dict[int, Tactician]
    profiler: Optional[Profiler] = None
    explainer: Optional[Explainer] = None
    max_decide_attempts: int = 2
    timings: dict = field(default_factory=dict)

    # -- nodes ----------------------------------------------------------------

    def _sense(self, state: GameState) -> Tuple[GameState, list]:
        """Snapshot the pre-move state and enumerate legal actions."""
        return state.clone(), self.validator.legal_actions(state)

    def _profile(self, state: GameState, tactician: Tactician):
        """Collect Profiler outputs for the DecisionContext."""
        profiles = None
        opponent_policy = None
        if self.profiler is not None:
            profiles = self.profiler.profiles(state.num_players)
            if tactician.uses_opponent_model:
                opponent_policy = self.profiler.predict
        return profiles, opponent_policy

    def _decide(self, ctx: DecisionContext, tactician: Tactician) -> Decision:
        return tactician.decide(ctx)

    def _fallback_decision(self, ctx: DecisionContext) -> Decision:
        """Deterministic safe move when the Tactician misbehaves twice."""
        ranked = rank_actions(ctx.state, ctx.legal)
        return Decision(action=ranked[0][0], report=None)

    # -- driver ---------------------------------------------------------------

    def run_turn(
        self, state: GameState, step_index: int
    ) -> Tuple[dict, MoveResult, Optional[RoundResult]]:
        """Execute one turn in place on ``state``.

        Returns ``(turn_record, move_result, round_result_or_None)``.
        The turn record matches docs/API.md's TurnRecord shape.
        """
        turn_start = time.perf_counter()
        player_index = state.current_player
        round_number = state.round_number
        tactician = self.tacticians[player_index]

        # sense
        state_before, legal = self._sense(state)
        if not legal:
            raise RuntimeError("no legal actions: state is inconsistent")

        # profile
        profiles, opponent_policy = self._profile(state, tactician)

        ctx = DecisionContext(
            state=state_before,
            player_index=player_index,
            legal=legal,
            profiles=profiles,
            opponent_policy=opponent_policy,
        )

        # decide -> validate loop (reject edge)
        decide_ms = 0.0
        validate_ms = 0.0
        attempts = 0
        decision: Optional[Decision] = None
        last_validation = None
        for _ in range(self.max_decide_attempts):
            t0 = time.perf_counter()
            candidate = self._decide(ctx, tactician)
            decide_ms += (time.perf_counter() - t0) * 1000

            t0 = time.perf_counter()
            validation = self.validator.validate(state, candidate.action)
            validate_ms += (time.perf_counter() - t0) * 1000
            attempts += 1
            last_validation = validation
            if validation.ok:
                decision = candidate
                break
            # Reject edge: re-sense legality and let the tactician retry.
            ctx = DecisionContext(
                state=state_before,
                player_index=player_index,
                legal=self.validator.legal_actions(state),
                profiles=profiles,
                opponent_policy=opponent_policy,
            )
        if decision is None:
            decision = self._fallback_decision(ctx)
            t0 = time.perf_counter()
            last_validation = self.validator.validate(state, decision.action)
            validate_ms += (time.perf_counter() - t0) * 1000
            attempts += 1
            if not last_validation.ok:  # pragma: no cover — engine bug
                raise RuntimeError(
                    "fallback action failed validation: "
                    f"{last_validation.violation}"
                )

        # execute
        move, round_result = step(state, decision.action)

        # observe
        if self.profiler is not None:
            self.profiler.observe(state_before, decision.action, move, decide_ms)

        # explain
        explain_ms = 0.0
        explanation = None
        if self.explainer is not None:
            t0 = time.perf_counter()
            explanation = self.explainer.explain(ctx, decision, move)
            explain_ms = (time.perf_counter() - t0) * 1000

        total_ms = (time.perf_counter() - turn_start) * 1000

        record = {
            "step": step_index,
            "round": round_number,
            "player_index": player_index,
            "player_name": state.players[player_index].name,
            "tactician": tactician.name,
            "action": decision.action.to_dict(),
            "state_before": state_before.to_dict(),
            "state_after": state.to_dict(),
            "explanation": explanation.to_dict() if explanation else None,
            "report": decision.report.to_dict() if decision.report else None,
            "profiles": (
                {
                    str(i): profile.to_dict()
                    for i, profile in profiles.items()
                    if i != player_index
                }
                if profiles
                else {}
            ),
            "validation": {
                "ok": bool(last_validation and last_validation.ok),
                "violation": (
                    {
                        "predicate": last_validation.violation.predicate,
                        "message": last_validation.violation.message,
                    }
                    if last_validation and last_validation.violation
                    else None
                ),
                "attempts": attempts,
            },
            "timing": {
                "decide_ms": round(decide_ms, 3),
                "validate_ms": round(validate_ms, 3),
                "explain_ms": round(explain_ms, 3),
                "total_ms": round(total_ms, 3),
            },
        }
        return record, move, round_result
