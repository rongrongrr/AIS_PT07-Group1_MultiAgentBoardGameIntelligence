"""Greedy heuristic Azul player — maximizes expected wall scoring.

Strategy:
1. For each legal action, simulate placing tiles on the pattern line.
2. Score each action based on:
   - Wall placement score if the pattern line would be completed.
   - Preference for nearly-complete pattern lines (fewer tiles needed).
   - Avoidance of floor penalties.
   - Bonus for placing tiles that contribute to end-game bonuses
     (completing rows, columns, or all-of-one-color).
3. Pick the highest-scoring action.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from tiles.azul.rules import (
    calculate_floor_penalty,
    count_tiles_of_color,
    get_legal_actions,
    get_pattern_line_color,
    pattern_line_space,
    score_tile_placement,
    wall_column_for_color,
)
from tiles.ml.base import MachinePlayer
from tiles.models.schemas import (
    DestinationType,
    GameAction,
    GameStateData,
    PlayerState,
    SourceType,
    TileColor,
)


@dataclass(frozen=True)
class Weights:
    """Heuristic weights. Different settings give different play styles
    (see ARCHETYPES), which the profiler is trained to recognise."""

    wall: float = 3.0        # immediate wall points when a line completes
    fill: float = 2.0        # progress towards completing a line
    row_pref: float = 0.3    # preference for small rows (complete faster)
    bonus: float = 1.0       # multiplier on end-game bonus progress terms
    overflow: float = 0.8    # weight on floor penalty from overflow
    floor: float = 1.0       # weight on floor penalty when dumping to floor
    block: float = 0.0       # reward for taking colours opponents are building
    loyalty: float = 0.0     # reward per tile of this colour already on own board
    volume: float = 0.0      # reward per tile taken (greedy for big piles)


DEFAULT_WEIGHTS = Weights()


def _block_value(state: GameStateData, player: PlayerState, action: GameAction) -> float:
    """How many opponent pattern lines in progress want this colour."""
    n = 0
    for opp in state.players:
        if opp.index == player.index and opp.name == player.name:
            continue
        for row in range(5):
            if get_pattern_line_color(opp, row) == action.color and pattern_line_space(opp, row) > 0:
                n += 1
    return float(n)


def _color_progress(player: PlayerState, color: TileColor) -> int:
    """Tiles of this colour already committed on the player's wall and pattern lines."""
    on_wall = sum(1 for r in range(5) if player.wall[r][wall_column_for_color(r, color)])
    in_lines = sum(1 for row in player.pattern_lines for t in row if t == color)
    return on_wall + in_lines


def _count_source_tiles(state: GameStateData, action: GameAction) -> int:
    """Count how many tiles the player would pick up from this source+color."""
    color = action.color
    if action.source_type == SourceType.FACTORY and action.source_index is not None:
        if action.source_index < len(state.factories):
            return count_tiles_of_color(state.factories[action.source_index], color)
    elif action.source_type == SourceType.CENTER:
        return count_tiles_of_color(
            [t for t in state.center_pool if t != "firstPlayer"], color
        )
    return 1


def _score_action(state: GameStateData, player: PlayerState, action: GameAction,
                  w: Weights = DEFAULT_WEIGHTS) -> float:
    """Score a single action. Higher = better."""
    n_tiles = _count_source_tiles(state, action)
    score = 0.0
    if w.block:
        score += _block_value(state, player, action) * w.block
    if w.loyalty:
        score += _color_progress(player, action.color) * w.loyalty
    if w.volume:
        score += n_tiles * w.volume

    if action.destination == DestinationType.FLOOR:
        # Sending tiles directly to floor is bad, only do as last resort
        current_floor = len(player.floor_line)
        penalty_now = calculate_floor_penalty(current_floor)
        penalty_after = calculate_floor_penalty(current_floor + n_tiles)
        score += (penalty_after - penalty_now) * w.floor  # negative number
        score -= 0.5  # slight extra penalty to prefer pattern lines
        return score

    row = action.destination_row
    if row is None:
        return -100

    color = action.color
    space = pattern_line_space(player, row)
    tiles_placed = min(n_tiles, space)
    overflow = max(0, n_tiles - space)

    # --- Base: wall placement score if pattern line completes this turn ---
    filled_after = (row + 1) - space + tiles_placed
    will_complete = filled_after >= (row + 1)

    if will_complete:
        col = wall_column_for_color(row, color)
        # Simulate: temporarily mark the wall position to score it
        wall_copy = [r[:] for r in player.wall]
        wall_copy[row][col] = True
        wall_score = score_tile_placement(wall_copy, row, col)
        score += wall_score * w.wall  # strong weight for immediate points
    else:
        # Partial fill — reward progress toward completion
        # Prefer rows that are closer to being full
        fill_ratio = filled_after / (row + 1)
        score += fill_ratio * w.fill

    # --- Prefer smaller rows (complete faster) ---
    score += (5 - row) * w.row_pref

    # --- End-game bonus potential ---
    col = wall_column_for_color(row, color)

    # Horizontal row progress
    row_filled = sum(1 for c in range(5) if player.wall[row][c])
    if will_complete:
        row_filled += 1
    if row_filled >= 3:
        score += row_filled * 0.5 * w.bonus

    # Vertical column progress
    col_filled = sum(1 for r in range(5) if player.wall[r][col])
    if will_complete:
        col_filled += 1
    if col_filled >= 3:
        score += col_filled * 0.5 * w.bonus

    # Color completion progress
    color_placed = 0
    for r in range(5):
        c = wall_column_for_color(r, color)
        if player.wall[r][c]:
            color_placed += 1
    if will_complete:
        color_placed += 1
    if color_placed >= 3:
        score += color_placed * 0.4 * w.bonus

    # --- Overflow penalty (excess tiles go to floor) ---
    if overflow > 0:
        current_floor = len(player.floor_line)
        penalty_now = calculate_floor_penalty(current_floor)
        penalty_after = calculate_floor_penalty(current_floor + overflow)
        score += (penalty_after - penalty_now) * w.overflow  # negative

    # --- First-player token penalty (taking from center first) ---
    if action.source_type == SourceType.CENTER:
        has_fp = "firstPlayer" in state.center_pool
        if has_fp and not player.has_first_player_token:
            # Taking first-player token = -1 floor penalty, but you go first
            score -= 0.5

    return score


ARCHETYPES = {
    "GreedyPlayer": DEFAULT_WEIGHTS,                                  # balanced
    "ColorCollectorPlayer": Weights(loyalty=1.5, bonus=3.0),          # sticks to colours it already holds
    "RusherPlayer": Weights(row_pref=3.0, fill=3.0, bonus=0.2),       # fills small rows fast
    "RecklessPlayer": Weights(volume=1.2, floor=0.2, overflow=0.1),   # grabs big piles, tolerates the floor
    "BlockerPlayer": Weights(block=3.0),                              # denies opponents' colours
}

# Styles an adaptive player may switch between (candidates for the best response).
COUNTER_STYLES = {
    "Balanced": DEFAULT_WEIGHTS,
    "Blocker": Weights(block=3.0),
    "HeavyBlocker": Weights(block=6.0),
}

logger = logging.getLogger(__name__)


class GreedyPlayer(MachinePlayer):
    """Greedy heuristic player that picks the highest-scoring legal action.

    ``weights`` selects the play style; the default is the balanced baseline.
    """

    _name = "GreedyPlayer"

    def __init__(self, weights: Optional[Weights] = None, seed: Optional[int] = None):
        self.weights = weights or ARCHETYPES.get(self._name, DEFAULT_WEIGHTS)
        # Why the last move was chosen: top alternatives with their heuristic scores.
        self.last_explanation: dict = {}

    @property
    def name(self) -> str:
        return self._name

    def score_breakdown(self, state: GameStateData, player_index: int, action: GameAction) -> float:
        return _score_action(state, state.players[player_index], action, self.weights)

    async def decide(self, game_state: GameStateData, player_index: int) -> GameAction:
        actions = get_legal_actions(game_state, player_index)
        if not actions:
            raise ValueError("No legal actions available")

        player = game_state.players[player_index]
        scored = [(a, _score_action(game_state, player, a, self.weights)) for a in actions]
        scored.sort(key=lambda x: x[1], reverse=True)

        best_action, best_score = scored[0]
        self.last_explanation = {
            "model": self.name,
            "chosen_score": round(best_score, 2),
            "n_legal": len(actions),
            "top_alternatives": [
                {"action": a.model_dump(), "score": round(sc, 2)} for a, sc in scored[:3]
            ],
        }
        logger.info(
            f"[{self.name}] Best: {best_action.color.value} from "
            f"{best_action.source_type.value}[{best_action.source_index}] -> "
            f"{best_action.destination.value}[{best_action.destination_row}] "
            f"(score={best_score:.1f}, {len(actions)} options)"
        )
        return best_action


def _variant(name: str):
    return type(name, (GreedyPlayer,), {"_name": name, "__doc__": f"{name}: GreedyPlayer with the {name} weights."})


ColorCollectorPlayer = _variant("ColorCollectorPlayer")
RusherPlayer = _variant("RusherPlayer")
RecklessPlayer = _variant("RecklessPlayer")
BlockerPlayer = _variant("BlockerPlayer")
