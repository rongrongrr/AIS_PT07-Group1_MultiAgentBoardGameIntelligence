"""Profile-conditioned Tactician.

Observes the opponents' moves, classifies their play-style with the trained
archetype classifier, and switches to the heuristic weights that scored best
against that archetype in simulation (models/best_response.json, produced by
scripts/best_response.py). Until enough opponent moves have been seen it plays
the balanced baseline, so it never does worse than ``GreedyPlayer`` by design
(whether it does *better* is measured by scripts/evaluate_adaptive.py).
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from tiles.ml.archetypes import DEFAULT_MODEL_PATH, ArchetypeClassifier, extract_features
from tiles.ml.greedy_player import ARCHETYPES, COUNTER_STYLES, DEFAULT_WEIGHTS, GreedyPlayer, Weights
from tiles.ml.rollout_player import RolloutPlayer
from tiles.models.schemas import GameAction, GameStateData

BEST_RESPONSE_PATH = Path(__file__).resolve().parents[2] / "models" / "best_response.json"

_classifier_cache: Dict[str, Optional[ArchetypeClassifier]] = {}


def _load_classifier() -> Optional[ArchetypeClassifier]:
    key = str(DEFAULT_MODEL_PATH)
    if key not in _classifier_cache:
        _classifier_cache[key] = ArchetypeClassifier.load(DEFAULT_MODEL_PATH) if DEFAULT_MODEL_PATH.exists() else None
    return _classifier_cache[key]


def _load_best_response() -> Dict[str, str]:
    if not BEST_RESPONSE_PATH.exists():
        return {}
    data = json.loads(BEST_RESPONSE_PATH.read_text())
    return {opp: entry["best"] for opp, entry in data.get("responses", {}).items()}


class AdaptivePlayer(GreedyPlayer):
    """GreedyPlayer whose weights are chosen from the inferred opponent archetype."""

    _name = "AdaptivePlayer"
    MIN_OBSERVED_MOVES = 6

    def __init__(self, classifier: Optional[ArchetypeClassifier] = None,
                 best_response: Optional[Dict[str, str]] = None, seed: Optional[int] = None):
        super().__init__(weights=DEFAULT_WEIGHTS)
        self.classifier = classifier if classifier is not None else _load_classifier()
        self.best_response = best_response if best_response is not None else _load_best_response()
        self.history: Dict[str, List[dict]] = defaultdict(list)

    def observe(self, record: dict, observer_name: str) -> None:
        if record["player_name"] != observer_name:
            self.history[record["player_name"]].append(record)

    def infer_opponents(self) -> Dict[str, dict]:
        """Archetype estimate per opponent with enough observed moves."""
        out = {}
        if self.classifier is None:
            return out
        for name, moves in self.history.items():
            if len(moves) < self.MIN_OBSERVED_MOVES:
                continue
            feats = extract_features(moves, name)
            if feats is None:
                continue
            pred = self.classifier.predict(feats)
            out[name] = {"archetype": pred.archetype, "confidence": pred.confidence,
                         "moves_observed": len(moves)}
        return out

    def choose_weights(self) -> tuple[Weights, dict]:
        inferred = self.infer_opponents()
        if not inferred:
            return DEFAULT_WEIGHTS, {"opponents": {}, "playing_as": "Balanced",
                                     "reason": "not enough opponent moves observed yet"}
        votes: Dict[str, float] = defaultdict(float)
        for est in inferred.values():
            votes[est["archetype"]] += est["confidence"]
        target = max(votes, key=votes.get)
        response = self.best_response.get(target, "Balanced")
        return COUNTER_STYLES.get(response, DEFAULT_WEIGHTS), {
            "opponents": inferred, "target_archetype": target, "playing_as": response,
            "reason": f"opponent looks like {target}; best simulated response is {response}",
        }

    async def decide(self, game_state: GameStateData, player_index: int) -> GameAction:
        self.weights, info = self.choose_weights()
        action = await super().decide(game_state, player_index)
        self.last_explanation["adaptation"] = info
        return action


class AdaptiveRolloutPlayer(RolloutPlayer):
    """Lookahead player whose simulated opponents play like their inferred archetype.

    The profiler (archetype classifier over observed moves) supplies each opponent's
    heuristic weights, so the rollouts predict *that* opponent's replies instead of
    assuming a generic one.
    """

    _name = "AdaptiveRolloutPlayer"
    MIN_OBSERVED_MOVES = 10
    MIN_CONFIDENCE = 0.5

    def __init__(self, classifier: Optional[ArchetypeClassifier] = None, seed: Optional[int] = None, **kw):
        super().__init__(seed=seed, **kw)
        self.classifier = classifier if classifier is not None else _load_classifier()
        self.history: Dict[str, List[dict]] = defaultdict(list)
        self._inferred: Dict[str, dict] = {}

    observe = AdaptivePlayer.observe
    infer_opponents = AdaptivePlayer.infer_opponents

    def opponent_weights(self, state: GameStateData) -> Dict[str, Weights]:
        # Only trust confident labels: the classifier is ~55% accurate overall, and simulating
        # the wrong opponent is worse than assuming a generic one.
        self._inferred = {n: e for n, e in self.infer_opponents().items()
                          if e["confidence"] >= self.MIN_CONFIDENCE}
        return {name: ARCHETYPES.get(est["archetype"], DEFAULT_WEIGHTS)
                for name, est in self._inferred.items()}

    async def decide(self, game_state: GameStateData, player_index: int) -> GameAction:
        action = await super().decide(game_state, player_index)
        self.last_explanation["adaptation"] = {
            "opponents": self._inferred,
            "playing_as": "lookahead",
            "reason": ("simulating opponents as: " + ", ".join(
                f"{n} ~ {e['archetype']}" for n, e in self._inferred.items()))
            if self._inferred else "not enough opponent moves observed yet; simulating balanced opponents",
        }
        return action
