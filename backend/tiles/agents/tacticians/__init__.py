"""Tactician registry.

Register implementations here so sessions can be configured by name
from the API/CLI. Search tacticians (minimax, mcts, mcts_profiled) are
imported lazily so the core stays importable without them.
"""

from __future__ import annotations

from typing import Callable, Dict

from tiles.agents.base import Tactician

from .greedy import GreedyTactician
from .random_tactician import RandomTactician


def _minimax(**kwargs) -> Tactician:
    from .minimax import MinimaxTactician

    return MinimaxTactician(**kwargs)


def _mcts(**kwargs) -> Tactician:
    from .mcts import MCTSTactician

    return MCTSTactician(**kwargs)


def _mcts_profiled(**kwargs) -> Tactician:
    from .mcts import MCTSTactician

    kwargs.setdefault("use_opponent_model", True)
    tactician = MCTSTactician(**kwargs)
    # Records/telemetry are keyed by the registry name, not the class.
    tactician.name = "mcts_profiled"
    return tactician


TACTICIANS: Dict[str, Callable[..., Tactician]] = {
    "random": RandomTactician,
    "greedy": GreedyTactician,
    "minimax": _minimax,
    "mcts": _mcts,
    "mcts_profiled": _mcts_profiled,
}


def make_tactician(name: str, **kwargs) -> Tactician:
    try:
        factory = TACTICIANS[name]
    except KeyError:
        raise ValueError(
            f"unknown tactician {name!r}; available: {sorted(TACTICIANS)}"
        ) from None
    return factory(**kwargs)


__all__ = [
    "TACTICIANS",
    "make_tactician",
    "GreedyTactician",
    "RandomTactician",
]
