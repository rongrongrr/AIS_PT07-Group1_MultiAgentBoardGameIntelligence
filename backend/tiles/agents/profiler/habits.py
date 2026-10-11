"""A Profiler whose predictor can also learn habits outside the move score.

``OpponentMovePredictor`` models a player by seven weights on the parts of the
move score. A player with a favourite colour, a dislike of the centre or a
liking for particular pattern lines has a habit none of those seven parts can
express. ``HabitPredictor`` adds twelve habit features (one per colour, one for
taking from the centre, one per pattern row and one for the floor) with their own
weights. The seven original weights are updated as before. The habit weights
start at zero and move by a fixed step whenever the model's guess was wrong:
up for the habits of the move actually played, down for those of the move it
guessed. This module is used by the ``opponent_styles`` experiment; the default
Profiler is unchanged.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from tiles.agents.tacticians.heuristics import score_action
from tiles.core import Action, GameState, legal_actions

from .basic import BasicProfiler
from .predictor import OpponentMovePredictor

NUM_COLOURS = 5
NUM_ROWS = 5

HABIT_KEYS = (
    [f"habit_colour_{c}" for c in range(NUM_COLOURS)]
    + ["habit_centre"]
    + [f"habit_row_{r}" for r in range(NUM_ROWS)]
    + ["habit_floor"]
)


def habit_features(action: Action) -> Dict[str, float]:
    """One-hot habit features of a move: colour, centre, and destination."""
    feats = {key: 0.0 for key in HABIT_KEYS}
    feats[f"habit_colour_{action.color}"] = 1.0
    if action.from_center:
        feats["habit_centre"] = 1.0
    if action.to_floor:
        feats["habit_floor"] = 1.0
    else:
        feats[f"habit_row_{action.dest_row}"] = 1.0
    return feats


class HabitPredictor(OpponentMovePredictor):
    """The seven-weight predictor plus additive habit weights."""

    def __init__(self, *args, habit_rate: float = 0.25, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.habit_rate = habit_rate

    def weights_for(self, player_index: int) -> Dict[str, float]:
        if player_index not in self._weights:
            self._weights[player_index] = {**self.prior, **{k: 0.0 for k in HABIT_KEYS}}
        return self._weights[player_index]

    def _components(self, state: GameState, legal: List[Action]) -> Dict[int, Dict[str, float]]:
        out = {}
        for a in legal:
            comps = dict(score_action(state, a)[1])
            comps.update(habit_features(a))
            out[a.action_id] = comps
        return out

    def observe(self, state_before: GameState, action: Action, player_index: Optional[int] = None) -> None:
        player = player_index if player_index is not None else state_before.current_player
        legal = legal_actions(state_before)
        if not legal:
            return
        components = self._components(state_before, legal)
        chosen = components.get(action.action_id)
        if chosen is None:
            return
        weights = self.weights_for(player)
        scores = self._scores(weights, components)
        predicted_id = max(scores, key=scores.get)
        if predicted_id != action.action_id:
            predicted = components[predicted_id]
            for key in weights:
                values = [comps.get(key, 0.0) for comps in components.values()]
                span = max(values) - min(values)
                if span <= 1e-9:
                    continue
                gradient = (chosen.get(key, 0.0) - predicted.get(key, 0.0)) / span
                if key.startswith("habit_"):
                    weights[key] += self.habit_rate * gradient
                else:
                    weights[key] *= math.exp(self.learning_rate * gradient)
        # Keep the seven original weights at the prior's overall scale.
        scale = sum(abs(w) for k, w in weights.items() if not k.startswith("habit_"))
        if scale > 0:
            factor = self.prior_scale / scale
            for key in weights:
                if not key.startswith("habit_"):
                    weights[key] *= factor
        self._observed[player] = self._observed.get(player, 0) + 1


class ExtendedProfiler(BasicProfiler):
    """``BasicProfiler`` with a predictor that also learns habits."""

    name = "extended"

    def __init__(self, learning_rate: float = 0.1, temperature: float = 2.0, k_prior: float = 6.0,
                 habit_rate: float = 0.25) -> None:
        super().__init__(learning_rate=learning_rate, temperature=temperature, k_prior=k_prior)
        self.predictor = HabitPredictor(
            learning_rate=learning_rate, temperature=temperature, k_prior=k_prior, habit_rate=habit_rate
        )
