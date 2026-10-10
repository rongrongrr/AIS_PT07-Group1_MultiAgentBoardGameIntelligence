"""BasicProfiler: the default Profiler implementation.

Composes the online feature accumulator (traits), the archetype
classifier, and the opponent-move predictor behind the ``Profiler``
interface from the Decision Stack contracts.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from tiles.agents.base import PlayerProfile, Profiler
from tiles.core import Action, GameState, MoveResult

from .archetypes import archetype_description, classify
from .features import PlayerFeatureAccumulator, move_features
from .predictor import OpponentMovePredictor


class BasicProfiler(Profiler):
    name = "basic"

    def __init__(
        self,
        learning_rate: float = 0.8,
        temperature: float = 2.0,
        k_prior: float = 6.0,
    ) -> None:
        self._accumulators: Dict[int, PlayerFeatureAccumulator] = {}
        self._names: Dict[int, str] = {}
        self.predictor = OpponentMovePredictor(
            learning_rate=learning_rate,
            temperature=temperature,
            k_prior=k_prior,
        )

    # -- Profiler interface ---------------------------------------------------

    def observe(
        self,
        state_before: GameState,
        action: Action,
        move: MoveResult,
        decision_ms: Optional[float] = None,
    ) -> None:
        player = move.player_index
        self._names[player] = state_before.players[player].name
        acc = self._accumulators.setdefault(
            player, PlayerFeatureAccumulator()
        )
        acc.add(move_features(state_before, action, move, decision_ms))
        self.predictor.observe(state_before, action, player)

    def profile(self, player_index: int) -> PlayerProfile:
        acc = self._accumulators.get(player_index)
        traits = acc.traits() if acc else {}
        moves = acc.n if acc else 0
        archetype, confidence = classify(traits)
        if moves == 0:
            confidence = 0.0
        name = self._names.get(player_index, f"player_{player_index}")
        return PlayerProfile(
            player_index=player_index,
            player_name=name,
            archetype=archetype,
            confidence=confidence,
            traits=traits,
            moves_observed=moves,
            summary=self._summarize(name, archetype, confidence, traits, moves),
        )

    def predict(
        self, state: GameState, player_index: int, legal: List[Action]
    ) -> Dict[int, float]:
        return self.predictor.predict(state, player_index, legal)

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _summarize(
        name: str,
        archetype: str,
        confidence: float,
        traits: Dict[str, float],
        moves: int,
    ) -> str:
        if moves == 0:
            return f"{name}: no moves observed yet."
        bits = [
            f"{name} ({archetype.replace('_', ' ')}, "
            f"{confidence:.0%} confidence): {moves} moves observed"
        ]
        if traits.get("denial_avg", 0.0) >= 0.3:
            bits.append(
                "frequently drafts colors opponents need "
                f"(denial {traits['denial_avg']:.2f})"
            )
        floor_rate = traits.get("floor_rate", 0.0)
        if floor_rate <= 0.15:
            bits.append(f"rarely overflows (floor rate {floor_rate:.0%})")
        elif floor_rate >= 0.4:
            bits.append(
                f"tolerates floor penalties (floor rate {floor_rate:.0%})"
            )
        if traits.get("completion_rate", 0.0) >= 0.5:
            bits.append(
                "reliably completes pattern lines "
                f"({traits['completion_rate']:.0%} of moves)"
            )
        if traits.get("color_bias", 0.0) >= 0.4:
            bits.append("shows a strong color preference")
        if traits.get("fpt_rate", 0.0) >= 0.25:
            bits.append("competes for the first-player token")
        tempo = traits.get("tempo_ms", 0.0)
        if tempo > 0:
            bits.append(f"avg decision {tempo:.0f}ms")
        summary = "; ".join(bits) + "."
        description = archetype_description(archetype)
        return f"{summary} {description}" if description else summary
