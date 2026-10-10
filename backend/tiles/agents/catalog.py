"""Human-readable catalog of the Decision Stack registry.

The registries (``tacticians.TACTICIANS``, ``profiler.PROFILERS``,
``explainer.EXPLAINERS``) are callables; this module adds the
descriptions and parameter schemas the UI needs to render agent cards
and configuration forms (``GET /api/agents``). Keep it in sync when a
new implementation is registered.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional


def _param(
    name: str,
    type_: str,
    default,
    description: str,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
    choices: Optional[List[str]] = None,
) -> dict:
    spec = {
        "name": name,
        "type": type_,
        "default": default,
        "description": description,
    }
    if minimum is not None:
        spec["min"] = minimum
    if maximum is not None:
        spec["max"] = maximum
    if choices:
        spec["choices"] = choices
    return spec


_SIMULATIONS = _param(
    "simulations", "int", 300,
    "MCTS simulations per decision (strength vs. latency).", 20, 5000,
)
_C_PUCT = _param(
    "c_puct", "float", 1.5,
    "Exploration constant in the PUCT selection formula.", 0.1, 5.0,
)

TACTICIAN_INFO: Dict[str, dict] = {
    "random": {
        "description": (
            "Uniform-random choice over the legal moves. The weakest "
            "baseline from the report's comparative evaluation."
        ),
        "params": [
            _param("seed", "int", None, "RNG seed for reproducible play."),
        ],
    },
    "greedy": {
        "description": (
            "Weighted heuristic over every legal move: immediate placement "
            "points, pattern-line progress, floor penalty, first-player "
            "token value, end-game bonus potential and denial of tiles "
            "opponents need. The report's heuristic Tactician; the "
            "per-component breakdown doubles as explainability evidence."
        ),
        "params": [],
    },
    "minimax": {
        "description": (
            "Depth-limited paranoid alpha-beta search within the current "
            "round, with a heuristic beam at non-root nodes. The report's "
            "minimax baseline."
        ),
        "params": [
            _param("depth", "int", 3, "Search depth in plies.", 1, 5),
            _param("beam_width", "int", 12, "Moves kept per non-root node.", 2, 40),
        ],
    },
    "mcts": {
        "description": (
            "PUCT Monte Carlo Tree Search with heuristic priors, "
            "determinized redeals at round boundaries and epsilon-greedy "
            "rollouts. Strong, opponent-agnostic search."
        ),
        "params": [_SIMULATIONS, _C_PUCT],
    },
    "mcts_profiled": {
        "description": (
            "The same PUCT search, but at opponent nodes the prior is "
            "blended with the Profiler's predicted move distribution, so "
            "search effort concentrates on futures the actual opponent is "
            "likely to create. The report's adaptive, opponent-aware "
            "Tactician."
        ),
        "params": [_SIMULATIONS, _C_PUCT],
    },
}

PROFILER_INFO: Dict[str, dict] = {
    "basic": {
        "description": (
            "Online behavioral profiler: accumulates nine traits per player "
            "(color bias, center/floor rates, completion, denial, risk, "
            "bonus focus, first-player token, tempo), classifies into five "
            "archetypes with a softmax confidence, and predicts each "
            "opponent's next move with a Bayesian prior→posterior softmax "
            "policy over heuristic components."
        ),
        "params": [
            _param("learning_rate", "float", 0.8, "Multiplicative-weights step size.", 0.05, 3.0),
            _param("temperature", "float", 2.0, "Softmax temperature of the predicted policy.", 0.2, 10.0),
            _param("k_prior", "float", 6.0, "Pseudo-count strength of the population prior.", 0.5, 50.0),
        ],
    },
}

EXPLAINER_INFO: Dict[str, dict] = {
    "template": {
        "description": (
            "Deterministic rationale from search artifacts: primary "
            "heuristic driver, margin over the runner-up, simulations and "
            "principal variation, Profiler evidence, and concept tags "
            "(COMPLETES_LINE, BLOCKS_OPPONENT, FLOOR_SACRIFICE, …)."
        ),
        "requires": None,
    },
    "llm": {
        "description": (
            "Template rationale rewritten by Claude as two sentences of "
            "live commentary. Facts come from the template layer; the LLM "
            "adds style only and silently falls back to the template."
        ),
        "requires": "ANTHROPIC_API_KEY",
    },
}

VALIDATOR_INFO = {
    "name": "validator",
    "class": "Validator",
    "description": (
        "Deterministic symbolic rules engine and per-turn coordinator: "
        "enumerates legal moves, checks every proposal against named "
        "predicates (wall_slot_open, line_color_matches, …), and bounces "
        "rejected proposals back to the Tactician with the violated "
        "predicate. No LLM is ever in this path."
    ),
}


def agents_catalog() -> dict:
    """The ``GET /api/agents`` payload."""
    from tiles.agents.explainer import EXPLAINERS
    from tiles.agents.profiler import PROFILERS
    from tiles.agents.tacticians import TACTICIANS, make_tactician

    tacticians = []
    for name in sorted(TACTICIANS):
        info = TACTICIAN_INFO.get(name, {})
        try:
            described = make_tactician(name).describe()
        except Exception:  # noqa: BLE001 — a broken registration shouldn't hide the rest
            described = {"class": "?", "uses_opponent_model": False}
        tacticians.append(
            {
                "name": name,
                "class": described.get("class", "?"),
                "description": info.get("description", ""),
                "uses_opponent_model": bool(described.get("uses_opponent_model")),
                "params": info.get("params", []),
            }
        )

    profilers = []
    for name in sorted(PROFILERS):
        info = PROFILER_INFO.get(name, {})
        profilers.append(
            {
                "name": name,
                "class": PROFILERS[name].__name__
                if hasattr(PROFILERS[name], "__name__")
                else "?",
                "description": info.get("description", ""),
                "params": info.get("params", []),
            }
        )

    explainers = []
    for name in sorted(EXPLAINERS):
        info = EXPLAINER_INFO.get(name, {})
        requires = info.get("requires")
        explainers.append(
            {
                "name": name,
                "class": EXPLAINERS[name].__name__
                if hasattr(EXPLAINERS[name], "__name__")
                else "?",
                "description": info.get("description", ""),
                "requires": requires,
                "available": not requires or bool(os.environ.get(requires)),
            }
        )

    return {
        "tacticians": tacticians,
        "profilers": profilers,
        "explainers": explainers,
        "validator": dict(VALIDATOR_INFO),
    }
