"""The Validator: deterministic rules gate.

The Validator is intentionally *not* an LLM and never guesses: it wraps
the symbolic rules engine (``tiles.core.rules``) and produces
machine-readable predicate failures. The turn orchestrator
(``tiles.orchestration.turn_graph``) routes a rejected proposal back to
the Tactician with the violation in ``DecisionContext.violation``,
forming the self-correcting loop described in the architecture report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from tiles.core import (
    Action,
    GameState,
    RuleViolation,
    check_action,
    legal_actions,
)


@dataclass
class ValidationResult:
    ok: bool
    violation: Optional[RuleViolation] = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "violation": (
                {
                    "predicate": self.violation.predicate,
                    "message": self.violation.message,
                }
                if self.violation
                else None
            ),
        }


@dataclass
class Validator:
    """Rules authority for one session. Stateless."""

    def legal_actions(self, state: GameState) -> List[Action]:
        return legal_actions(state)

    def validate(self, state: GameState, action: Action) -> ValidationResult:
        violation = check_action(state, action)
        return ValidationResult(ok=violation is None, violation=violation)
