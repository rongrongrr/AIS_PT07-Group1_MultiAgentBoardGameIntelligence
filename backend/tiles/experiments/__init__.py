"""TILES experiments: the report's evaluation deliverables as runnable,
trackable jobs.

Every experiment kind lives in :mod:`tiles.experiments.kinds` and is
described by an :class:`ExperimentSpec` (parameters, report section,
how to run). :class:`ExperimentManager` runs them in the background,
persists progress and results in the ledger, and streams events to the
UI; the CLI (``tiles experiment run <kind>``) runs the same code
synchronously. Results share one shape (``summary`` / ``metrics`` /
``tables`` / ``series`` / ``raw``, see docs/API.md) so the frontend can
render any experiment without special-casing.
"""

from .registry import (
    EXPERIMENTS,
    ExperimentSpec,
    ParamSpec,
    get_spec,
    list_specs,
    validate_params,
)
from .runner import ExperimentContext, ExperimentManager

__all__ = [
    "EXPERIMENTS",
    "ExperimentContext",
    "ExperimentManager",
    "ExperimentSpec",
    "ParamSpec",
    "get_spec",
    "list_specs",
    "validate_params",
]
