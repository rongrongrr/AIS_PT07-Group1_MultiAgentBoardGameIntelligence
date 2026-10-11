"""Experiment registry: specs, parameter schemas, validation.

An :class:`ExperimentSpec` is the self-description of one experiment
kind — what it measures, which report section it feeds, its parameter
schema (served to the UI as a form), and the ``run`` callable. The
registry is populated lazily from :mod:`tiles.experiments.kinds` so kind
modules can import these dataclasses without a circular import.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

#: Kind modules, in the order they are listed to the UI.
_KIND_MODULES = (
    "profiler_ablation",
    "prediction_accuracy",
    "archetype_discovery",
    "tournament",
    "search_budget_sweep",
    "rule_extraction",
    "latency_profile",
    "xai_coverage",
    "heuristic_comparison",
    "player_count_scaling",
)


@dataclass(frozen=True)
class ParamSpec:
    """One experiment parameter, as shown in the UI form."""

    name: str
    type: str  # "int" | "float" | "str" | "bool"
    default: Any
    description: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    choices: Optional[Tuple[str, ...]] = None

    def to_dict(self) -> dict:
        out: Dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "default": self.default,
            "min": self.min,
            "max": self.max,
            "description": self.description,
        }
        if self.choices:
            out["choices"] = list(self.choices)
        return out

    def coerce(self, value: Any) -> Any:
        """Coerce ``value`` to this parameter's type and range-check it.
        Raises ``ValueError`` with a message naming the parameter."""
        try:
            if self.type == "int":
                if isinstance(value, bool):
                    raise ValueError
                if isinstance(value, float) and not value.is_integer():
                    raise ValueError
                out: Any = int(value)
            elif self.type == "float":
                out = float(value)
            elif self.type == "bool":
                if isinstance(value, str):
                    lowered = value.strip().lower()
                    if lowered in ("true", "1", "yes", "on"):
                        out = True
                    elif lowered in ("false", "0", "no", "off", ""):
                        out = False
                    else:
                        raise ValueError
                else:
                    out = bool(value)
            else:
                out = str(value)
        except (TypeError, ValueError):
            raise ValueError(
                f"parameter {self.name!r} must be of type {self.type}, got {value!r}"
            ) from None
        if self.type in ("int", "float"):
            if self.min is not None and out < self.min:
                raise ValueError(
                    f"parameter {self.name!r} must be >= {self.min}, got {out}"
                )
            if self.max is not None and out > self.max:
                raise ValueError(
                    f"parameter {self.name!r} must be <= {self.max}, got {out}"
                )
        if self.choices and out not in self.choices:
            raise ValueError(
                f"parameter {self.name!r} must be one of {list(self.choices)}, got {out!r}"
            )
        return out


@dataclass(frozen=True)
class ExperimentSpec:
    """Self-description of one experiment kind."""

    name: str
    title: str
    description: str
    report_section: str
    estimated: str
    params: Tuple[ParamSpec, ...]
    #: run(params, ctx) -> ExperimentResult dict (docs/API.md)
    run: Callable[[dict, Any], dict] = field(repr=False, compare=False)
    #: optional cross-field validation; raise ValueError on bad input
    validate: Optional[Callable[[dict], None]] = field(
        default=None, repr=False, compare=False
    )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "report_section": self.report_section,
            "estimated": self.estimated,
            "params": [p.to_dict() for p in self.params],
        }

    def defaults(self) -> dict:
        return {p.name: p.default for p in self.params}


#: Populated on first use by :func:`_load` (lazy, see module docstring).
EXPERIMENTS: Dict[str, ExperimentSpec] = {}


def _load() -> Dict[str, ExperimentSpec]:
    if not EXPERIMENTS:
        for module_name in _KIND_MODULES:
            module = importlib.import_module(
                f"tiles.experiments.kinds.{module_name}"
            )
            spec: ExperimentSpec = module.SPEC
            EXPERIMENTS[spec.name] = spec
    return EXPERIMENTS


def list_specs() -> List[ExperimentSpec]:
    return list(_load().values())


def get_spec(kind: str) -> ExperimentSpec:
    try:
        return _load()[kind]
    except KeyError:
        raise ValueError(
            f"unknown experiment kind {kind!r}; available: {sorted(_load())}"
        ) from None


def validate_params(kind: str, params: Optional[dict]) -> dict:
    """Apply defaults, coerce types, range-check, reject unknown keys.

    Returns the complete, normalized parameter dict for ``kind``.
    """
    spec = get_spec(kind)
    params = dict(params or {})
    known = {p.name for p in spec.params}
    unknown = set(params) - known
    if unknown:
        raise ValueError(
            f"unknown parameter(s) for {kind!r}: {sorted(unknown)}; "
            f"accepted: {sorted(known)}"
        )
    out: Dict[str, Any] = {}
    for p in spec.params:
        value = params.get(p.name, p.default)
        if value is None:
            value = p.default
        out[p.name] = p.coerce(value)
    if spec.validate is not None:
        spec.validate(out)
    return out
