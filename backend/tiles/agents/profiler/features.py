"""Per-move feature extraction and online per-player aggregation.

``move_features`` turns one observed move into a flat numeric feature
dict; ``PlayerFeatureAccumulator`` folds those into normalized behavioral
traits (all 0..1 unless noted) that feed archetype classification.
"""

from __future__ import annotations

from typing import Dict, Optional

from tiles.agents.tacticians.heuristics import score_action
from tiles.core import Action, GameState, MoveResult, NUM_COLORS, COLOR_NAMES


def move_features(
    state_before: GameState,
    action: Action,
    move: MoveResult,
    decision_ms: Optional[float] = None,
) -> Dict[str, float]:
    """Features of one move, computed against the pre-move state.

    ``state_before.current_player`` must be the mover (it is, whenever
    this is called from a Profiler.observe hook).
    """
    from tiles.core import legal_actions  # local import to avoid cycles

    _, components = score_action(state_before, action)
    feats: Dict[str, float] = {}
    for color in range(NUM_COLORS):
        feats[f"color_{COLOR_NAMES[color]}"] = (
            1.0 if action.color == color else 0.0
        )
    feats["from_center"] = 1.0 if action.from_center else 0.0
    feats["to_floor"] = 1.0 if action.to_floor else 0.0
    feats["overflow_tiles"] = float(move.tiles_to_floor)
    feats["completed_line"] = 1.0 if move.completed_line else 0.0
    feats["took_fpt"] = 1.0 if move.took_first_player_token else 0.0
    feats["immediate_points"] = components["immediate_points"]
    feats["denial"] = components["denial"]
    feats["floor_penalty"] = components["floor_penalty"]
    feats["bonus_potential"] = components["bonus_potential"]
    feats["n_legal"] = float(len(legal_actions(state_before)))
    feats["decision_ms"] = float(decision_ms or 0.0)
    return feats


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


class PlayerFeatureAccumulator:
    """Online aggregation of one player's move features into traits.

    Trait normalizations (documented ranges):

    * ``color_bias``    — (max color share − 0.2) / 0.8; 0 = uniform draft,
                          1 = always the same color.
    * ``center_rate``   — share of moves drafting from the center.
    * ``floor_rate``    — share of moves that put any tile on the floor
                          (deliberate floor dumps or overflow).
    * ``completion_rate`` — share of moves that complete a pattern line.
    * ``denial_avg``    — mean denial component, clamped to 0..1 (realized
                          per-move denial rarely exceeds 1; a mean of 0.3+
                          marks a deliberate blocker).
    * ``risk_avg``      — mean |floor penalty points| / 3.
    * ``bonus_focus``   — mean bonus-potential component / 6 (completing
                          moves carry 2–4 points of bonus progress).
    * ``fpt_rate``      — share of moves taking the first-player token.
    * ``immediate_avg`` — mean immediate placement points / 5.
    * ``tempo_ms``      — mean decision time in ms (NOT 0..1; excluded
                          from archetype distance calculations).
    """

    def __init__(self) -> None:
        self.n = 0
        self.color_counts = [0] * NUM_COLORS
        self.center_moves = 0
        self.floor_moves = 0
        self.completed_moves = 0
        self.fpt_moves = 0
        self.denial_sum = 0.0
        self.risk_sum = 0.0
        self.bonus_sum = 0.0
        self.immediate_sum = 0.0
        self.decision_ms_sum = 0.0
        self.decision_ms_n = 0

    def add(self, feats: Dict[str, float]) -> None:
        self.n += 1
        for color in range(NUM_COLORS):
            if feats.get(f"color_{COLOR_NAMES[color]}", 0.0):
                self.color_counts[color] += 1
        self.center_moves += int(feats.get("from_center", 0.0))
        if feats.get("to_floor", 0.0) or feats.get("overflow_tiles", 0.0) > 0:
            self.floor_moves += 1
        self.completed_moves += int(feats.get("completed_line", 0.0))
        self.fpt_moves += int(feats.get("took_fpt", 0.0))
        self.denial_sum += feats.get("denial", 0.0)
        self.risk_sum += abs(feats.get("floor_penalty", 0.0))
        self.bonus_sum += feats.get("bonus_potential", 0.0)
        self.immediate_sum += feats.get("immediate_points", 0.0)
        if feats.get("decision_ms", 0.0) > 0:
            self.decision_ms_sum += feats["decision_ms"]
            self.decision_ms_n += 1

    def traits(self) -> Dict[str, float]:
        if self.n == 0:
            return {}
        n = self.n
        max_share = max(self.color_counts) / n
        return {
            "color_bias": _clamp01((max_share - 0.2) / 0.8),
            "center_rate": self.center_moves / n,
            "floor_rate": self.floor_moves / n,
            "completion_rate": self.completed_moves / n,
            "denial_avg": _clamp01(self.denial_sum / n),
            "risk_avg": _clamp01(self.risk_sum / n / 3.0),
            "bonus_focus": _clamp01(self.bonus_sum / n / 6.0),
            "fpt_rate": self.fpt_moves / n,
            "immediate_avg": _clamp01(self.immediate_sum / n / 5.0),
            "tempo_ms": (
                self.decision_ms_sum / self.decision_ms_n
                if self.decision_ms_n
                else 0.0
            ),
        }
