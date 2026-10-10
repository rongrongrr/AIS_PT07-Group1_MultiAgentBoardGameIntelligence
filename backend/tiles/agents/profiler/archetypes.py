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
# PlayerFeatureAccumulator.traits(). They are *data-calibrated*: each
# signature is the centroid of the trait vectors realized by the
# reference preset that defines the archetype (20 games per preset,
# calibration seed 11, see experiments/kinds/archetype_discovery.py).
# Competent play clusters tightly (completion ~0.6, center ~0.5), so the
# archetypes differ mainly on the discriminative traits — denial, floor
# and risk rates, first-player-token rate, bonus focus — and distances
# are measured in *standardized* units (TRAIT_SCALE = pooled standard
# deviation of each trait over the calibration population) so that a
# low-variance trait like denial_avg counts as much as a noisy one like
# center_rate. tempo_ms is deliberately excluded.
ARCHETYPES: Dict[str, dict] = {
    "aggressive_blocker": {
        "description": (
            "Drafts tiles opponents visibly need; plays the player, "
            "not just the board."
        ),
        "signature": {
            "color_bias": 0.081,
            "center_rate": 0.572,
            "floor_rate": 0.240,
            "completion_rate": 0.602,
            "denial_avg": 0.292,
            "risk_avg": 0.260,
            "bonus_focus": 0.420,
            "fpt_rate": 0.152,
            "immediate_avg": 0.400,
        },
    },
    "cautious_optimizer": {
        "description": (
            "Minimizes floor penalties, fills lines it can complete, "
            "avoids speculative picks and rarely takes the first-player token."
        ),
        "signature": {
            "color_bias": 0.079,
            "center_rate": 0.500,
            "floor_rate": 0.175,
            "completion_rate": 0.626,
            "denial_avg": 0.104,
            "risk_avg": 0.146,
            "bonus_focus": 0.411,
            "fpt_rate": 0.055,
            "immediate_avg": 0.402,
        },
    },
    "set_collector": {
        "description": (
            "Chases color sets and column bonuses; completes lines for "
            "bonus progress over immediate points."
        ),
        "signature": {
            "color_bias": 0.071,
            "center_rate": 0.523,
            "floor_rate": 0.182,
            "completion_rate": 0.651,
            "denial_avg": 0.158,
            "risk_avg": 0.164,
            "bonus_focus": 0.465,
            "fpt_rate": 0.099,
            "immediate_avg": 0.406,
        },
    },
    "greedy_scorer": {
        "description": (
            "Maximizes points now: completes lines for immediate wall "
            "placements, opportunistic rather than positional."
        ),
        "signature": {
            "color_bias": 0.074,
            "center_rate": 0.522,
            "floor_rate": 0.196,
            "completion_rate": 0.637,
            "denial_avg": 0.159,
            "risk_avg": 0.171,
            "bonus_focus": 0.435,
            "fpt_rate": 0.101,
            "immediate_avg": 0.433,
        },
    },
    "risk_taker": {
        "description": (
            "Grabs the first-player token and drafts from the center to "
            "control tempo; accepts floor penalties; volatile scoring."
        ),
        "signature": {
            "color_bias": 0.069,
            "center_rate": 0.580,
            "floor_rate": 0.196,
            "completion_rate": 0.634,
            "denial_avg": 0.208,
            "risk_avg": 0.191,
            "bonus_focus": 0.452,
            "fpt_rate": 0.164,
            "immediate_avg": 0.412,
        },
    },
}

#: Pooled standard deviation of each trait over the calibration
#: population; distances are measured in these units.
TRAIT_SCALE: Dict[str, float] = {
    "color_bias": 0.031,
    "center_rate": 0.055,
    "floor_rate": 0.060,
    "completion_rate": 0.042,
    "denial_avg": 0.109,
    "risk_avg": 0.082,
    "bonus_focus": 0.057,
    "fpt_rate": 0.053,
    "immediate_avg": 0.052,
}

# Softmax temperature for the confidence, in standardized-distance units.
_SOFTMAX_TEMP = 0.3


def _distance(traits: Dict[str, float], signature: Dict[str, float]) -> float:
    """RMS *standardized* distance over the signature's keys (missing
    traits count as 0; each difference is divided by the trait's pooled
    standard deviation)."""
    sq = sum(
        ((traits.get(key, 0.0) - target) / TRAIT_SCALE.get(key, 1.0)) ** 2
        for key, target in signature.items()
    )
    return math.sqrt(sq / len(signature))


def standardize(vectors: List[Sequence[float]]) -> List[List[float]]:
    """Z-score each column of ``vectors`` (pure Python); constant columns
    are left at 0. Used before clustering so every trait counts equally."""
    if not vectors:
        return []
    dim = len(vectors[0])
    n = len(vectors)
    means = [sum(v[d] for v in vectors) / n for d in range(dim)]
    stds = [
        math.sqrt(sum((v[d] - means[d]) ** 2 for v in vectors) / n)
        for d in range(dim)
    ]
    return [
        [
            (v[d] - means[d]) / stds[d] if stds[d] > 1e-12 else 0.0
            for d in range(dim)
        ]
        for v in vectors
    ]


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
