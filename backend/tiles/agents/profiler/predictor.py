"""Opponent next-move prediction.

Models each opponent as a softmax policy over the shared heuristic's
score components, with a per-player weight vector. Cold start uses the
population prior (``DEFAULT_WEIGHTS``, i.e. "people mostly play sound
Azul"); every observed move applies a multiplicative-weights update, so
the posterior drifts toward that player's revealed preferences — the
Bayesian prior-to-posterior transition from the report, without any ML
dependency and fully deterministic.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from tiles.agents.tacticians.heuristics import DEFAULT_WEIGHTS, score_action
from tiles.core import Action, GameState, legal_actions


class OpponentMovePredictor:
    """Per-player learned softmax policy over heuristic components."""

    def __init__(
        self,
        prior_weights: Optional[Dict[str, float]] = None,
        learning_rate: float = 0.8,
        temperature: float = 2.0,
        k_prior: float = 6.0,
    ) -> None:
        self.prior = dict(prior_weights or DEFAULT_WEIGHTS)
        self.prior_scale = sum(abs(w) for w in self.prior.values())
        self.learning_rate = learning_rate
        self.temperature = temperature
        self.k_prior = k_prior
        self._weights: Dict[int, Dict[str, float]] = {}
        self._observed: Dict[int, int] = {}

    # -- internals -----------------------------------------------------------

    def weights_for(self, player_index: int) -> Dict[str, float]:
        if player_index not in self._weights:
            self._weights[player_index] = dict(self.prior)
        return self._weights[player_index]

    def moves_observed(self, player_index: int) -> int:
        return self._observed.get(player_index, 0)

    def _components(
        self, state: GameState, legal: List[Action]
    ) -> Dict[int, Dict[str, float]]:
        return {a.action_id: score_action(state, a)[1] for a in legal}

    def _scores(
        self,
        weights: Dict[str, float],
        components: Dict[int, Dict[str, float]],
    ) -> Dict[int, float]:
        return {
            aid: sum(weights[k] * v for k, v in comps.items())
            for aid, comps in components.items()
        }

    # -- learning ------------------------------------------------------------

    def observe(
        self,
        state_before: GameState,
        action: Action,
        player_index: Optional[int] = None,
    ) -> None:
        """Update the mover's weight vector from one observed choice.

        Structured-perceptron with exponentiated weights: when the
        current model would have predicted a *different* action, raise
        the weights of components where the actually-chosen action beats
        the model's pick and lower the others (range-normalized). When
        the model already ranks the chosen action first, no update — so
        weights only move to fix ranking mistakes and stay stable
        otherwise. Weights stay positive; the vector is rescaled to keep
        the prior's overall norm.
        """
        player = (
            player_index
            if player_index is not None
            else state_before.current_player
        )
        legal = legal_actions(state_before)
        if not legal:
            return
        components = self._components(state_before, legal)
        chosen = components.get(action.action_id)
        if chosen is None:  # not legal from this state; ignore quietly
            return

        weights = self.weights_for(player)
        scores = self._scores(weights, components)
        predicted_id = max(scores, key=scores.get)
        if predicted_id != action.action_id:
            predicted = components[predicted_id]
            for key in weights:
                values = [
                    comps.get(key, 0.0) for comps in components.values()
                ]
                span = max(values) - min(values)
                if span <= 1e-9:
                    continue  # component carries no signal this turn
                gradient = (
                    chosen.get(key, 0.0) - predicted.get(key, 0.0)
                ) / span  # in [-1, 1]
                weights[key] *= math.exp(self.learning_rate * gradient)

        # Rescale so the weight vector keeps the prior's overall scale.
        scale = sum(abs(w) for w in weights.values())
        if scale > 0:
            factor = self.prior_scale / scale
            for key in weights:
                weights[key] *= factor

        self._observed[player] = self._observed.get(player, 0) + 1

    # -- prediction ----------------------------------------------------------

    def predict(
        self, state: GameState, player_index: int, legal: List[Action]
    ) -> Dict[int, float]:
        """Distribution over ``legal`` (keyed by action_id).

        Softmax of the player's learned weighted scores, blended with a
        uniform distribution. The blend factor grows with observations,
        starting from a small pseudo-count so the population prior
        speaks even before any moves are seen:

            alpha = (n + n0) / (n + n0 + k),  n0 = 3
        """
        if not legal:
            return {}
        weights = self.weights_for(player_index)
        components = self._components(state, legal)
        scores = self._scores(weights, components)

        max_score = max(scores.values())
        exps = {
            aid: math.exp((s - max_score) / self.temperature)
            for aid, s in scores.items()
        }
        total = sum(exps.values())
        softmax = {aid: e / total for aid, e in exps.items()}

        n = self.moves_observed(player_index)
        alpha = (n + 3.0) / (n + 3.0 + self.k_prior)
        uniform = 1.0 / len(legal)
        return {
            aid: alpha * p + (1.0 - alpha) * uniform
            for aid, p in softmax.items()
        }

    def top_k(
        self,
        state: GameState,
        player_index: int,
        legal: List[Action],
        k: int = 3,
    ) -> List[int]:
        dist = self.predict(state, player_index, legal)
        return [
            aid
            for aid, _ in sorted(
                dist.items(), key=lambda item: item[1], reverse=True
            )[:k]
        ]
