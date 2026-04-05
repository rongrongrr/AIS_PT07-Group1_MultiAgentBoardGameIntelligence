"""Azul game rules engine — validation, legal moves, and state transitions."""

from __future__ import annotations

from typing import List, Optional, Tuple

from app.models.schemas import (
    DestinationType,
    GameAction,
    GameStateData,
    PlayerState,
    SourceType,
    TileColor,
)

# The fixed wall pattern for standard Azul.
# wall[row][col] = which color belongs there.
WALL_PATTERN: List[List[TileColor]] = [
    [TileColor.BLUE, TileColor.YELLOW, TileColor.RED, TileColor.BLACK, TileColor.WHITE],
    [TileColor.WHITE, TileColor.BLUE, TileColor.YELLOW, TileColor.RED, TileColor.BLACK],
    [TileColor.BLACK, TileColor.WHITE, TileColor.BLUE, TileColor.YELLOW, TileColor.RED],
    [TileColor.RED, TileColor.BLACK, TileColor.WHITE, TileColor.BLUE, TileColor.YELLOW],
    [TileColor.YELLOW, TileColor.RED, TileColor.BLACK, TileColor.WHITE, TileColor.BLUE],
]

FLOOR_PENALTIES = [-1, -1, -2, -2, -2, -3, -3]


def wall_column_for_color(row: int, color: TileColor) -> int:
    """Return the column index where a given color goes on the given wall row."""
    return WALL_PATTERN[row].index(color)


def is_color_on_wall(player: PlayerState, row: int, color: TileColor) -> bool:
    """Check if a color is already placed on a player's wall in the given row."""
    col = wall_column_for_color(row, color)
    return player.wall[row][col]


def get_pattern_line_color(player: PlayerState, row: int) -> Optional[TileColor]:
    """Get the color currently occupying a pattern line row, or None if empty."""
    line = player.pattern_lines[row]
    for tile in line:
        if tile is not None:
            return tile
    return None


def pattern_line_space(player: PlayerState, row: int) -> int:
    """Return how many empty slots remain on a pattern line row."""
    capacity = row + 1
    filled = sum(1 for t in player.pattern_lines[row] if t is not None)
    return capacity - filled


def can_place_on_pattern_line(player: PlayerState, row: int, color: TileColor) -> bool:
    """Check if tiles of the given color can be placed on the pattern line row."""
    if is_color_on_wall(player, row, color):
        return False
    existing_color = get_pattern_line_color(player, row)
    if existing_color is not None and existing_color != color:
        return False
    if pattern_line_space(player, row) == 0:
        return False
    return True


def get_factory_tiles(state: GameStateData, factory_index: int) -> List[TileColor]:
    """Get tiles in a specific factory."""
    if factory_index < 0 or factory_index >= len(state.factories):
        return []
    return list(state.factories[factory_index])


def get_center_tile_colors(state: GameStateData) -> List[TileColor]:
    """Get distinct pickable colors from the center pool (excludes firstPlayer token)."""
    colors = set()
    for tile in state.center_pool:
        if tile != "firstPlayer":
            try:
                colors.add(TileColor(tile))
            except ValueError:
                pass
    return list(colors)


def count_tiles_of_color(tiles: List, color: TileColor) -> int:
    """Count how many tiles of a specific color are in a list."""
    return sum(1 for t in tiles if str(t) == str(color.value))


def get_legal_actions(state: GameStateData, player_index: int) -> List[GameAction]:
    """
    Generate all legal actions for a player given the current game state.

    An action in Azul is: pick all tiles of one color from a source (factory or center),
    then place them on a pattern line row or the floor.
    """
    if player_index < 0 or player_index >= len(state.players):
        return []

    player = state.players[player_index]
    actions = []

    sources: List[Tuple[SourceType, Optional[int], List[TileColor]]] = []

    # Factories
    for i, factory in enumerate(state.factories):
        colors_in_factory = set()
        for tile in factory:
            if isinstance(tile, TileColor):
                colors_in_factory.add(tile)
            else:
                try:
                    colors_in_factory.add(TileColor(str(tile)))
                except ValueError:
                    pass
        for color in colors_in_factory:
            sources.append((SourceType.FACTORY, i, color))

    # Center pool
    for color in get_center_tile_colors(state):
        sources.append((SourceType.CENTER, None, color))

    # For each source+color, enumerate valid destinations
    for source_type, source_index, color in sources:
        # Pattern line destinations
        for row in range(5):
            if can_place_on_pattern_line(player, row, color):
                actions.append(GameAction(
                    source_type=source_type,
                    source_index=source_index,
                    color=color,
                    destination=DestinationType.PATTERN_LINE,
                    destination_row=row,
                ))

        # Floor is always a valid destination
        actions.append(GameAction(
            source_type=source_type,
            source_index=source_index,
            color=color,
            destination=DestinationType.FLOOR,
            destination_row=None,
        ))

    return actions


def score_tile_placement(wall: List[List[bool]], row: int, col: int) -> int:
    """
    Calculate the score for placing a tile at wall[row][col].
    Score = length of contiguous horizontal line + length of contiguous vertical line.
    If isolated (no neighbors), score is 1.
    """
    h_count = 1
    # Count left
    c = col - 1
    while c >= 0 and wall[row][c]:
        h_count += 1
        c -= 1
    # Count right
    c = col + 1
    while c < 5 and wall[row][c]:
        h_count += 1
        c += 1

    v_count = 1
    # Count up
    r = row - 1
    while r >= 0 and wall[r][col]:
        v_count += 1
        r -= 1
    # Count down
    r = row + 1
    while r < 5 and wall[r][col]:
        v_count += 1
        r += 1

    if h_count == 1 and v_count == 1:
        return 1
    score = 0
    if h_count > 1:
        score += h_count
    if v_count > 1:
        score += v_count
    return score


def calculate_floor_penalty(floor_count: int) -> int:
    """Calculate total penalty for tiles on the floor line."""
    penalty = 0
    for i in range(min(floor_count, len(FLOOR_PENALTIES))):
        penalty += FLOOR_PENALTIES[i]
    return penalty


def calculate_end_game_bonuses(wall: List[List[bool]]) -> dict:
    """Calculate end-of-game bonuses."""
    horizontal = 0
    vertical = 0
    color_complete = 0

    # Complete horizontal rows: +2 each
    for row in range(5):
        if all(wall[row]):
            horizontal += 1

    # Complete vertical columns: +7 each
    for col in range(5):
        if all(wall[row][col] for row in range(5)):
            vertical += 1

    # All 5 of one color on wall: +10 each
    for color in TileColor.all_colors():
        positions = []
        for row in range(5):
            col = wall_column_for_color(row, color)
            positions.append(wall[row][col])
        if all(positions):
            color_complete += 1

    return {
        "horizontal": horizontal * 2,
        "vertical": vertical * 7,
        "color": color_complete * 10,
        "total": horizontal * 2 + vertical * 7 + color_complete * 10,
    }


def is_game_over(state: GameStateData) -> bool:
    """Check if any player has completed a horizontal wall row (triggers final round)."""
    for player in state.players:
        for row in range(5):
            if all(player.wall[row]):
                return True
    return False
