"""Reinforcement learning: a TD(0)-trained linear value function over after-states.

The value of a position is ``V(s) = w . phi(s)`` where ``phi`` summarises the position from one
player's point of view (score margin, pending line points, floor cost, board structure, ...).
Training plays self-play games; after each of a player's moves it applies the temporal-difference
update ``w += alpha * (r + V(s') - V(s)) * phi(s)``, where ``s``/``s'`` are the player's consecutive
after-states and ``r`` is the change in score margin banked in between (round scoring) plus the
final result at the end of the game. The player then picks the move whose after-state has the
highest value (epsilon-greedy while training).

This is deliberately a small, transparent RL method (linear function approximation) so that what
it learned can be read off the weights; scripts/train_td.py trains it and reports how it plays.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

from app.azul.game import GameSim, apply_action, floor_size, round_over
from app.azul.rules import (
    calculate_floor_penalty,
    get_legal_actions,
    score_tile_placement,
    wall_column_for_color,
)
from app.ml.greedy_player import DEFAULT_WEIGHTS, GreedyPlayer
from app.ml.rollout_player import _sim_from_state
from app.models.schemas import GameAction, GameStateData, PlayerState, TileColor

DEFAULT_TD_PATH = Path(__file__).resolve().parents[2] / "models" / "td_weights.json"

FEATURES = [
    "score_margin", "pending_line_points", "floor_cost", "line_progress", "wall_tiles",
    "row_structure", "column_structure", "color_structure", "token", "tiles_left",
    "pending_x_tiles_left", "bias",
]


def _player_features(p: PlayerState) -> np.ndarray:
    pending = 0.0
    progress = 0.0
    for r in range(5):
        filled = len(p.pattern_lines[r])
        if filled == r + 1:
            col = wall_column_for_color(r, p.pattern_lines[r][0])
            wall = [row[:] for row in p.wall]
            wall[r][col] = True
            pending += score_tile_placement(wall, r, col)
        elif filled:
            progress += (filled / (r + 1)) * (r + 1) ** 0.5
    wall_tiles = sum(sum(row) for row in p.wall)
    rows = sum(sum(row) ** 2 for row in p.wall) / 25.0
    cols = sum(sum(p.wall[r][c] for r in range(5)) ** 2 for c in range(5)) / 25.0
    colors = sum(sum(p.wall[r][wall_column_for_color(r, color)] for r in range(5)) ** 2
                 for color in TileColor.all_colors()) / 25.0
    floor = calculate_floor_penalty(floor_size(p))
    return np.array([p.score, pending, floor, progress, wall_tiles, rows, cols, colors,
                     1.0 if p.has_first_player_token else 0.0], dtype=float)


def features(state: GameStateData, me: int) -> np.ndarray:
    """Position features from ``me``'s point of view (mine minus the opponents' average)."""
    mine = _player_features(state.players[me])
    others = [_player_features(p) for i, p in enumerate(state.players) if i != me]
    opp = sum(others) / max(1, len(others))
    diff = mine - opp
    tiles_left = (sum(len(f) for f in state.factories)
                  + sum(1 for t in state.center_pool if t != "firstPlayer")) / 20.0
    scale = np.array([50.0, 10.0, 14.0, 10.0, 10.0, 5.0, 5.0, 5.0, 1.0])
    d = diff / scale
    return np.concatenate([d, [tiles_left, d[1] * tiles_left, 1.0]])


class TDPlayer(GreedyPlayer):
    """Plays the move whose after-state has the highest learned value."""

    _name = "TDPlayer"

    def __init__(self, w: Optional[np.ndarray] = None, epsilon: float = 0.0, seed: Optional[int] = None):
        super().__init__(weights=DEFAULT_WEIGHTS)
        self.w = np.array(w if w is not None else self._load_default(), dtype=float)
        self.epsilon = epsilon
        self._rng = random.Random(seed)

    @staticmethod
    def _load_default() -> np.ndarray:
        if DEFAULT_TD_PATH.exists():
            return np.array(json.loads(DEFAULT_TD_PATH.read_text())["w"], dtype=float)
        return np.zeros(len(FEATURES))

    def value(self, state: GameStateData, me: int) -> float:
        return float(self.w @ features(state, me))

    def afterstates(self, state: GameStateData, me: int) -> List[tuple]:
        """(action, features of the position after the action) for every legal action."""
        sim0 = _sim_from_state(state, me, random.Random(0))
        out = []
        for a in get_legal_actions(state, me):
            sim = sim0.copy()
            apply_action(sim, a)
            out.append((a, features(sim.state, me)))
        return out

    async def decide(self, game_state: GameStateData, player_index: int) -> GameAction:
        options = self.afterstates(game_state, player_index)
        if not options:
            raise ValueError("No legal actions available")
        if self.epsilon and self._rng.random() < self.epsilon:
            action, phi = self._rng.choice(options)
        else:
            action, phi = max(options, key=lambda o: float(self.w @ o[1]))
        self.last_phi = phi
        ranked = sorted(options, key=lambda o: float(self.w @ o[1]), reverse=True)[:3]
        self.last_explanation = {
            "model": self.name, "chosen_score": round(float(self.w @ phi), 3), "n_legal": len(options),
            "method": "TD(0)-learned linear value of the position after each move",
            "top_alternatives": [{"action": a.model_dump(), "score": round(float(self.w @ f), 3)} for a, f in ranked],
        }
        return action

    def save(self, path: Path = DEFAULT_TD_PATH, meta: Optional[dict] = None) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"features": FEATURES, "w": self.w.tolist(), "meta": meta or {}}, indent=2))


def td_update(w: np.ndarray, prev_phi: np.ndarray, reward: float, next_phi: Optional[np.ndarray],
              alpha: float) -> float:
    """One TD(0) step; ``next_phi`` None means the game ended (terminal value 0). Returns the TD error."""
    target = reward + (float(w @ next_phi) if next_phi is not None else 0.0)
    delta = target - float(w @ prev_phi)
    w += alpha * delta * prev_phi
    return delta
