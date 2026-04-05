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

from typing import List

from app.azul.rules import (
    WALL_PATTERN,
    calculate_floor_penalty,
    can_place_on_pattern_line,
    count_tiles_of_color,
    get_legal_actions,
    pattern_line_space,
    score_tile_placement,
    wall_column_for_color,
)
from app.ml.base import MachinePlayer
from app.models.schemas import (
    DestinationType,
    GameAction,
    GameStateData,
    PlayerState,
    SourceType,
    TileColor,
)


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


def _score_action(state: GameStateData, player: PlayerState, action: GameAction) -> float:
    """Score a single action. Higher = better."""
    score = 0.0
    n_tiles = _count_source_tiles(state, action)

    if action.destination == DestinationType.FLOOR:
        # Sending tiles directly to floor is bad, only do as last resort
        current_floor = len(player.floor_line)
        penalty_now = calculate_floor_penalty(current_floor)
        penalty_after = calculate_floor_penalty(current_floor + n_tiles)
        score = (penalty_after - penalty_now) * 1.0  # negative number
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
        score += wall_score * 3.0  # strong weight for immediate points
    else:
        # Partial fill — reward progress toward completion
        # Prefer rows that are closer to being full
        fill_ratio = filled_after / (row + 1)
        score += fill_ratio * 2.0

    # --- Prefer smaller rows (complete faster) ---
    score += (5 - row) * 0.3

    # --- End-game bonus potential ---
    col = wall_column_for_color(row, color)

    # Horizontal row progress
    row_filled = sum(1 for c in range(5) if player.wall[row][c])
    if will_complete:
        row_filled += 1
    if row_filled >= 3:
        score += row_filled * 0.5

    # Vertical column progress
    col_filled = sum(1 for r in range(5) if player.wall[r][col])
    if will_complete:
        col_filled += 1
    if col_filled >= 3:
        score += col_filled * 0.5

    # Color completion progress
    color_placed = 0
    for r in range(5):
        c = wall_column_for_color(r, color)
        if player.wall[r][c]:
            color_placed += 1
    if will_complete:
        color_placed += 1
    if color_placed >= 3:
        score += color_placed * 0.4

    # --- Overflow penalty (excess tiles go to floor) ---
    if overflow > 0:
        current_floor = len(player.floor_line)
        penalty_now = calculate_floor_penalty(current_floor)
        penalty_after = calculate_floor_penalty(current_floor + overflow)
        score += (penalty_after - penalty_now) * 0.8  # negative

    # --- First-player token penalty (taking from center first) ---
    if action.source_type == SourceType.CENTER:
        has_fp = "firstPlayer" in state.center_pool
        if has_fp and not player.has_first_player_token:
            # Taking first-player token = -1 floor penalty, but you go first
            score -= 0.5

    return score


class GreedyPlayer(MachinePlayer):
    """Greedy heuristic player that picks the highest-scoring legal action."""

    @property
    def name(self) -> str:
        return "GreedyPlayer"

    async def decide(self, game_state: GameStateData, player_index: int) -> GameAction:
        actions = get_legal_actions(game_state, player_index)
        if not actions:
            raise ValueError("No legal actions available")

        player = game_state.players[player_index]
        scored = [(a, _score_action(game_state, player, a)) for a in actions]
        scored.sort(key=lambda x: x[1], reverse=True)

        best_action, best_score = scored[0]
        logger.info(
            f"[GreedyPlayer] Best: {best_action.color.value} from "
            f"{best_action.source_type.value}[{best_action.source_index}] -> "
            f"{best_action.destination.value}[{best_action.destination_row}] "
            f"(score={best_score:.1f}, {len(actions)} options)"
        )
        return best_action


import logging
logger = logging.getLogger(__name__)
