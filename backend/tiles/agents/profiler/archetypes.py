"""Player archetypes: rule-based classification + offline clustering.

Five archetypes (the report's deliverable is 3–5 distinct player
archetypes). Classification is distance-to-signature with a softmax
confidence, so it works from the very first observed moves; ``KMeans``
supports offline archetype *discovery* over many recorded players
(pure Python, no numpy).
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Sequence, Tuple

# Trait signatures live on the same 0..1 scales produced by
# PlayerFeatureAccumulator.traits(). They are calibrated against the
# *realized* trait ranges of simulated players (competent play clusters
# tightly: completion ~0.6, center ~0.55, denial ~0.15), so the
# signatures encode deviations from sound baseline play rather than
# caricatures. tempo_ms is deliberately excluded.
ARCHETYPES: Dict[str, dict] = {
    "aggressive_blocker": {
        "description": (
            "Drafts tiles opponents visibly need; plays the player, "
            "not just the board."
        ),
        "signature": {
            "color_bias": 0.08,
            "center_rate": 0.55,
            "floor_rate": 0.28,
            "completion_rate": 0.55,
            "denial_avg": 0.30,
            "risk_avg": 0.30,
            "bonus_focus": 0.40,
            "fpt_rate": 0.18,
            "immediate_avg": 0.35,
        },
    },
    "cautious_optimizer": {
        "description": (
            "Minimizes floor penalties, fills lines it can complete, "
            "avoids speculative picks."
        ),
        "signature": {
            "color_bias": 0.08,
            "center_rate": 0.40,
            "floor_rate": 0.08,
            "completion_rate": 0.75,
            "denial_avg": 0.10,
            "risk_avg": 0.08,
            "bonus_focus": 0.45,
            "fpt_rate": 0.06,
            "immediate_avg": 0.50,
        },
    },
    "set_collector": {
        "description": (
            "Chases color sets and column bonuses; strong color "
            "preferences over immediate points."
        ),
        "signature": {
            "color_bias": 0.15,
            "center_rate": 0.50,
            "floor_rate": 0.15,
            "completion_rate": 0.68,
            "denial_avg": 0.12,
            "risk_avg": 0.15,
            "bonus_focus": 0.55,
            "fpt_rate": 0.10,
            "immediate_avg": 0.42,
        },
    },
    "greedy_scorer": {
        "description": (
            "Maximizes points now: completes lines for immediate wall "
            "placements, opportunistic rather than positional."
        ),
        "signature": {
            "color_bias": 0.08,
            "center_rate": 0.55,
            "floor_rate": 0.20,
            "completion_rate": 0.72,
            "denial_avg": 0.15,
            "risk_avg": 0.20,
            "bonus_focus": 0.45,
            "fpt_rate": 0.13,
            "immediate_avg": 0.55,
        },
    },
    "risk_taker": {
        "description": (
            "Accepts floor penalties and grabs the first-player token to "
            "control tempo; volatile scoring."
        ),
        "signature": {
            "color_bias": 0.10,
            "center_rate": 0.65,
            "floor_rate": 0.45,
            "completion_rate": 0.50,
            "denial_avg": 0.18,
            "risk_avg": 0.45,
            "bonus_focus": 0.40,
            "fpt_rate": 0.30,
            "immediate_avg": 0.35,
        },
    },
}

_SOFTMAX_TEMP = 0.05


def _distance(traits: Dict[str, float], signature: Dict[str, float]) -> float:
    """RMS distance over the signature's keys (missing traits count as 0)."""
    sq = sum(
        (traits.get(key, 0.0) - target) ** 2
        for key, target in signature.items()
    )
    return math.sqrt(sq / len(signature))


def classify(traits: Dict[str, float]) -> Tuple[str, float]:
    """Nearest-archetype classification with a softmax confidence.

    Returns ``(archetype_name, confidence)``; confidence is the softmax
    probability of the winning archetype over negative distances.
    """
    distances = {
        name: _distance(traits, spec["signature"])
        for name, spec in ARCHETYPES.items()
    }
    best = min(distances, key=distances.get)
    weights = {
        name: math.exp(-d / _SOFTMAX_TEMP) for name, d in distances.items()
    }
    total = sum(weights.values())
    return best, weights[best] / total


def archetype_description(name: str) -> str:
    return ARCHETYPES.get(name, {}).get("description", "")


class KMeans:
    """Minimal pure-Python k-means for offline archetype discovery.

    Vectors are plain lists of floats. Deterministic given ``seed``.
    """

    def __init__(self) -> None:
        self.centroids: List[List[float]] = []

    @staticmethod
    def _dist2(a: Sequence[float], b: Sequence[float]) -> float:
        return sum((x - y) ** 2 for x, y in zip(a, b))

    def fit(
        self,
        vectors: List[Sequence[float]],
        k: int,
        seed: int = 0,
        iters: int = 100,
    ) -> KMeans:
        if not vectors or k <= 0:
            raise ValueError("need at least one vector and k >= 1")
        k = min(k, len(vectors))
        rng = random.Random(seed)

        # k-means++ initialisation
        centroids = [list(rng.choice(vectors))]
        while len(centroids) < k:
            d2 = [
                min(self._dist2(v, c) for c in centroids) for v in vectors
            ]
            total = sum(d2)
            if total == 0:
                centroids.append(list(rng.choice(vectors)))
                continue
            pick = rng.random() * total
            acc = 0.0
            for v, d in zip(vectors, d2):
                acc += d
                if acc >= pick:
                    centroids.append(list(v))
                    break

        for _ in range(iters):
            assignments = [
                min(range(k), key=lambda i: self._dist2(v, centroids[i]))
                for v in vectors
            ]
            new_centroids = []
            for i in range(k):
                members = [
                    v for v, a in zip(vectors, assignments) if a == i
                ]
                if members:
                    dim = len(members[0])
                    new_centroids.append(
                        [
                            sum(m[d] for m in members) / len(members)
                            for d in range(dim)
                        ]
                    )
                else:  # empty cluster: reseed on a random point
                    new_centroids.append(list(rng.choice(vectors)))
            if new_centroids == centroids:
                break
            centroids = new_centroids

        self.centroids = centroids
        return self

    def predict(self, vector: Sequence[float]) -> int:
        if not self.centroids:
            raise ValueError("fit() must be called first")
        return min(
            range(len(self.centroids)),
            key=lambda i: self._dist2(vector, self.centroids[i]),
        )
