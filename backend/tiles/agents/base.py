"""Decision Stack contracts.

The four roles from the TILES architecture, expressed as interfaces so
implementations are swappable without touching the orchestrator or the
Play Engine:

* **Tactician** — proposes a move from the legal set it is handed.
* **Profiler** — observes opponents, classifies play styles, and
  predicts opponents' next moves (a probability distribution used to
  bias MCTS).
* **Explainer** — turns search artifacts and profiles into
  human-readable rationales.
* **Validator** — the deterministic rules gate and per-turn coordinator
  (see ``tiles.agents.validator`` / ``tiles.orchestration``).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from tiles.core import Action, GameState, MoveResult


# ---------------------------------------------------------------------------
# Shared decision artifacts
# ---------------------------------------------------------------------------


@dataclass
class PlayerProfile:
    """Behavioral profile of one player, produced by a Profiler."""

    player_index: int
    player_name: str
    archetype: str  # one of tiles.agents.profiler.archetypes.ARCHETYPES
    confidence: float  # 0..1
    traits: Dict[str, float] = field(default_factory=dict)
    moves_observed: int = 0
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "player_index": self.player_index,
            "player_name": self.player_name,
            "archetype": self.archetype,
            "confidence": round(self.confidence, 3),
            "traits": {k: round(v, 3) for k, v in self.traits.items()},
            "moves_observed": self.moves_observed,
            "summary": self.summary,
        }


@dataclass
class DecisionContext:
    """Everything a Tactician gets for one turn."""

    state: GameState
    player_index: int
    legal: List[Action]
    # Profiler outputs (may be None when no profiler is attached):
    profiles: Optional[Dict[int, PlayerProfile]] = None
    # opponent_policy(state, player_index, legal) -> {action_id: prob};
    # injected by the orchestrator so search-based tacticians can bias
    # opponent nodes with the Profiler's predictions.
    opponent_policy: Optional[object] = None
    time_budget_ms: Optional[float] = None
    rng_seed: Optional[int] = None


@dataclass
class CandidateMove:
    """One evaluated alternative, for explainability."""

    action: Action
    score: float  # Q-value (search) or heuristic score
    visits: int = 0
    prior: float = 0.0
    principal_variation: List[Action] = field(default_factory=list)
    notes: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "action": self.action.to_dict(),
            "score": round(self.score, 4),
            "visits": self.visits,
            "prior": round(self.prior, 4),
            "principal_variation": [
                a.to_dict() for a in self.principal_variation
            ],
            "notes": {k: round(v, 4) for k, v in self.notes.items()},
        }


@dataclass
class SearchReport:
    """Artifacts of a decision, consumed by the Explainer and the ledger.

    ``candidates`` is sorted best-first and includes the chosen move at
    index 0. Heuristic tacticians fill ``score``/``notes``; search
    tacticians additionally fill ``visits``/``prior``/``principal_variation``.
    """

    candidates: List[CandidateMove] = field(default_factory=list)
    simulations: int = 0
    elapsed_ms: float = 0.0
    used_opponent_model: bool = False
    notes: Dict[str, object] = field(default_factory=dict)

    @property
    def best(self) -> Optional[CandidateMove]:
        return self.candidates[0] if self.candidates else None

    @property
    def runner_up(self) -> Optional[CandidateMove]:
        return self.candidates[1] if len(self.candidates) > 1 else None

    def to_dict(self) -> dict:
        return {
            "candidates": [c.to_dict() for c in self.candidates[:8]],
            "simulations": self.simulations,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "used_opponent_model": self.used_opponent_model,
            "notes": self.notes,
        }


@dataclass
class Decision:
    """A Tactician's answer for one turn."""

    action: Action
    report: Optional[SearchReport] = None


@dataclass
class Explanation:
    """Explainer output for one decision."""

    text: str
    concepts: List[str] = field(default_factory=list)  # semantic tags
    evidence: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "concepts": self.concepts,
            "evidence": self.evidence,
        }


# ---------------------------------------------------------------------------
# Role interfaces
# ---------------------------------------------------------------------------


class Tactician(abc.ABC):
    """Proposes one legal move per turn."""

    #: registry key; subclasses must override
    name: str = "tactician"
    #: True when the tactician exploits Profiler predictions
    uses_opponent_model: bool = False

    @abc.abstractmethod
    def decide(self, ctx: DecisionContext) -> Decision:
        ...

    def describe(self) -> dict:
        return {
            "name": self.name,
            "uses_opponent_model": self.uses_opponent_model,
            "class": type(self).__name__,
        }


class Profiler(abc.ABC):
    """Observes moves, classifies archetypes, predicts opponent moves."""

    name: str = "profiler"

    @abc.abstractmethod
    def observe(
        self,
        state_before: GameState,
        action: Action,
        move: MoveResult,
        decision_ms: Optional[float] = None,
    ) -> None:
        """Ingest one observed move (state is pre-move)."""

    @abc.abstractmethod
    def profile(self, player_index: int) -> PlayerProfile:
        ...

    @abc.abstractmethod
    def predict(
        self, state: GameState, player_index: int, legal: List[Action]
    ) -> Dict[int, float]:
        """Probability distribution over ``legal`` keyed by action_id."""

    def profiles(self, num_players: int) -> Dict[int, PlayerProfile]:
        return {i: self.profile(i) for i in range(num_players)}


class Explainer(abc.ABC):
    """Builds natural-language rationales from decision artifacts."""

    name: str = "explainer"

    @abc.abstractmethod
    def explain(
        self,
        ctx: DecisionContext,
        decision: Decision,
        move: Optional[MoveResult] = None,
    ) -> Explanation:
        ...
