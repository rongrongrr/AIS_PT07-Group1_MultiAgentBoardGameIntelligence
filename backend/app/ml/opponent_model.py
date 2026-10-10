"""Opponent move prediction.

An opponent is modelled as a softmax-rational player: in a given position it picks move ``a``
with probability proportional to ``exp(score_style(a) / temperature)``, where ``score_style`` is the
heuristic move score under one of a library of play styles. From the moves observed so far, the
model computes a posterior over styles (likelihood of the observed moves under each style) and
predicts the next move as the posterior-weighted mixture of the styles' move distributions.

It generalises to opponents that are not in the library (e.g. lookahead players or humans) only
to the extent that their moves resemble some style's preferences; ``scripts/evaluate_opponent_model.py``
measures exactly that.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from app.azul.rules import get_legal_actions
from app.ml.greedy_player import ARCHETYPES, COUNTER_STYLES, Weights, _score_action
from app.models.schemas import GameAction, GameStateData

STYLE_LIBRARY: Dict[str, Weights] = {
    **ARCHETYPES,
    **{f"counter:{k}": v for k, v in COUNTER_STYLES.items() if k != "Balanced"},
}


def move_distribution(state: GameStateData, player_index: int, weights: Weights,
                      temperature: float) -> Tuple[List[GameAction], List[float]]:
    """Softmax over the heuristic scores of the player's legal moves."""
    actions = get_legal_actions(state, player_index)
    if not actions:
        return [], []
    player = state.players[player_index]
    scores = [_score_action(state, player, a, weights) / temperature for a in actions]
    m = max(scores)
    exps = [math.exp(s - m) for s in scores]
    z = sum(exps)
    return actions, [e / z for e in exps]


class OpponentModel:
    def __init__(self, styles: Optional[Dict[str, Weights]] = None, temperature: float = 1.0,
                 floor_prob: float = 1e-3):
        self.styles = styles or STYLE_LIBRARY
        self.temperature = temperature
        self.floor_prob = floor_prob          # one surprising move must not zero a style forever
        self.log_lik: Dict[str, float] = {name: 0.0 for name in self.styles}
        self.observed = 0

    def reset(self) -> None:
        self.log_lik = {name: 0.0 for name in self.styles}
        self.observed = 0

    def observe(self, state: GameStateData, player_index: int, action: GameAction) -> None:
        """Update the style posterior with a move the opponent made in ``state``."""
        for name, w in self.styles.items():
            actions, probs = move_distribution(state, player_index, w, self.temperature)
            p = next((pr for a, pr in zip(actions, probs) if a == action), 0.0)
            self.log_lik[name] += math.log(max(p, self.floor_prob))
        self.observed += 1

    def posterior(self) -> Dict[str, float]:
        m = max(self.log_lik.values())
        exps = {n: math.exp(v - m) for n, v in self.log_lik.items()}
        z = sum(exps.values())
        return {n: e / z for n, e in exps.items()}

    def predict(self, state: GameStateData, player_index: int, k: int = 3) -> List[Tuple[GameAction, float]]:
        """Top-k most likely next moves with probabilities (posterior-weighted mixture)."""
        post = self.posterior()
        mix: Dict[tuple, float] = {}
        by_key: Dict[tuple, GameAction] = {}
        for name, w in self.styles.items():
            actions, probs = move_distribution(state, player_index, w, self.temperature)
            for a, pr in zip(actions, probs):
                key = (a.source_type, a.source_index, a.color, a.destination, a.destination_row)
                by_key[key] = a
                mix[key] = mix.get(key, 0.0) + post[name] * pr
        ranked = sorted(mix.items(), key=lambda kv: kv[1], reverse=True)[:k]
        return [(by_key[key], p) for key, p in ranked]

    def likely_style(self) -> Tuple[str, float]:
        post = self.posterior()
        name = max(post, key=post.get)
        return name, post[name]
