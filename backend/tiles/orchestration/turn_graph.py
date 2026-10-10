"""Validator-coordinated turn pipeline.

This is the runnable expression of the report's LangGraph design: a
deterministic graph whose nodes mutate a shared per-turn state, with the
Validator gating every state transition. Node -> report mapping:

    sense    -> "sensing the state"        (snapshot + legal actions)
    profile  -> "profiling the opponent"   (Profiler outputs injected)
    decide   -> "searching for moves"      (Tactician proposal)
    validate -> "validating the move"      (Validator gate; reject edge
                 routes back to `decide` once, then to a greedy fallback)
    execute  -> state transition            (tiles.core.step locally; the
                 live adapter emits to the site instead)
    observe  -> Profiler ingests the move
    explain  -> "explaining the choice"    (Explainer rationale)

The graph is framework-free on purpose (no LLM decides routing — edges
are explicit Python control flow), which is exactly the property the
report selects LangGraph for; swapping this class for a
``langgraph.StateGraph`` is a mechanical translation of the same nodes.

The pipeline is split in two halves so local and live play share the
same decision logic:

* :meth:`TurnPipeline.propose` runs sense → profile → decide → validate
  and returns a :class:`Proposal` (no state mutation);
* :meth:`TurnPipeline.conclude` runs observe → explain and builds the
  TurnRecord, given however the move was executed.

:meth:`TurnPipeline.run_turn` chains both around the local engine's
``step``; the live adapter chains them around a Socket.IO emit.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from tiles.agents.base import (
    Decision,
    DecisionContext,
    Explainer,
    PlayerProfile,
    Profiler,
    Tactician,
)
from tiles.agents.tacticians.heuristics import rank_actions
from tiles.agents.validator import ValidationResult, Validator
from tiles.core import (
    Action,
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
class Proposal:
    """Output of the sense → profile → decide → validate half-turn."""

    ctx: DecisionContext
    decision: Decision
    validation: ValidationResult
    attempts: int
    profiles: Optional[Dict[int, PlayerProfile]]
    decide_ms: float
    validate_ms: float
    tactician: Tactician

    @property
    def action(self) -> Action:
        return self.decision.action


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

    # -- half turns -------------------------------------------------------------

    def propose(self, state: GameState) -> Proposal:
        """sense → profile → decide → validate (with the reject edge).

        Leaves ``state`` untouched; the returned proposal's action has
        passed the Validator and is safe to execute.
        """
        player_index = state.current_player
        tactician = self.tacticians[player_index]

        state_before, legal = self._sense(state)
        if not legal:
            raise RuntimeError("no legal actions: state is inconsistent")
        profiles, opponent_policy = self._profile(state, tactician)

        ctx = DecisionContext(
            state=state_before,
            player_index=player_index,
            legal=legal,
            profiles=profiles,
            opponent_policy=opponent_policy,
        )

        decide_ms = 0.0
        validate_ms = 0.0
        attempts = 0
        decision: Optional[Decision] = None
        last_validation: Optional[ValidationResult] = None
        for _attempt in range(self.max_decide_attempts):
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

        return Proposal(
            ctx=ctx,
            decision=decision,
            validation=last_validation,
            attempts=attempts,
            profiles=profiles,
            decide_ms=decide_ms,
            validate_ms=validate_ms,
            tactician=tactician,
        )

    def conclude(
        self,
        proposal: Proposal,
        move: Optional[MoveResult],
        state_after: Optional[GameState],
        step_index: int,
        extra_timing: Optional[Dict[str, float]] = None,
        extra_validation: Optional[dict] = None,
        turn_start: Optional[float] = None,
    ) -> dict:
        """observe → explain, then build the TurnRecord (docs/API.md)."""
        ctx = proposal.ctx
        state_before = ctx.state

        if self.profiler is not None and move is not None:
            self.profiler.observe(
                state_before, proposal.action, move, proposal.decide_ms
            )

        explain_ms = 0.0
        explanation = None
        if self.explainer is not None:
            t0 = time.perf_counter()
            explanation = self.explainer.explain(ctx, proposal.decision, move)
            explain_ms = (time.perf_counter() - t0) * 1000

        timing = {
            "decide_ms": round(proposal.decide_ms, 3),
            "validate_ms": round(proposal.validate_ms, 3),
        }
        for key, value in (extra_timing or {}).items():
            timing[key] = round(value, 3)
        timing["explain_ms"] = round(explain_ms, 3)
        if turn_start is not None:
            timing["total_ms"] = round((time.perf_counter() - turn_start) * 1000, 3)
        else:
            timing["total_ms"] = round(sum(timing.values()), 3)

        validation = {
            "ok": bool(proposal.validation and proposal.validation.ok),
            "violation": (
                {
                    "predicate": proposal.validation.violation.predicate,
                    "message": proposal.validation.violation.message,
                }
                if proposal.validation and proposal.validation.violation
                else None
            ),
            "attempts": proposal.attempts,
        }
        validation.update(extra_validation or {})

        profiles = proposal.profiles
        return {
            "step": step_index,
            "round": state_before.round_number,
            "player_index": ctx.player_index,
            "player_name": state_before.players[ctx.player_index].name,
            "tactician": proposal.tactician.name,
            "action": proposal.action.to_dict(),
            "state_before": state_before.to_dict(),
            "state_after": state_after.to_dict() if state_after is not None else None,
            "explanation": explanation.to_dict() if explanation else None,
            "report": (
                proposal.decision.report.to_dict()
                if proposal.decision.report
                else None
            ),
            "profiles": (
                {
                    str(i): profile.to_dict()
                    for i, profile in profiles.items()
                    if i != ctx.player_index
                }
                if profiles
                else {}
            ),
            "validation": validation,
            "timing": timing,
        }

    # -- driver ---------------------------------------------------------------

    def run_turn(
        self, state: GameState, step_index: int
    ) -> Tuple[dict, MoveResult, Optional[RoundResult]]:
        """Execute one turn in place on ``state`` (local engine).

        Returns ``(turn_record, move_result, round_result_or_None)``.
        The turn record matches docs/API.md's TurnRecord shape.
        """
        turn_start = time.perf_counter()
        proposal = self.propose(state)
        move, round_result = step(state, proposal.action)
        record = self.conclude(
            proposal, move, state, step_index, turn_start=turn_start
        )
        return record, move, round_result
