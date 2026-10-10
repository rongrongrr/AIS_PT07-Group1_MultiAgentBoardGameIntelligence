"""Profiler registry and public exports."""

from __future__ import annotations

from typing import Callable, Dict

from tiles.agents.base import Profiler

from .archetypes import ARCHETYPES, KMeans, archetype_description, classify
from .basic import BasicProfiler
from .features import PlayerFeatureAccumulator, move_features
from .predictor import OpponentMovePredictor

PROFILERS: Dict[str, Callable[..., Profiler]] = {
    "basic": BasicProfiler,
}


def make_profiler(name: str, **kwargs) -> Profiler:
    try:
        factory = PROFILERS[name]
    except KeyError:
        raise ValueError(
            f"unknown profiler {name!r}; available: {sorted(PROFILERS)}"
        ) from None
    return factory(**kwargs)


__all__ = [
    "ARCHETYPES",
    "BasicProfiler",
    "KMeans",
    "OpponentMovePredictor",
    "PROFILERS",
    "PlayerFeatureAccumulator",
    "archetype_description",
    "classify",
    "make_profiler",
    "move_features",
]
