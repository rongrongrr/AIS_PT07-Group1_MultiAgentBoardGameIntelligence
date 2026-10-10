"""Translate between the site's authoritative game object and tiles.core.

Mapping notes (verified against the Milestone-1 parser and its tests):

* ``game.players`` is a dict keyed by player name whose insertion order
  is the seat order; ``currentPlayer`` is a NAME and must be resolved to
  an index.
* Pattern lines arrive as ``{"lines": [[cell x (row+1)] x 5]}`` with row
  0 holding one slot — the same orientation as ``tiles.core``. A cell is
  ``{"selected": bool, "color"/"type": str}``; unselected cells are
  empty slots.
* The wall arrives as a positional 5x5 ``{"grid": ...}`` in the standard
  Azul orientation (row 0 = blue yellow red black white), which matches
  ``tiles.core.wall_color_at`` exactly, so ``selected`` flags map 1:1
  onto wall bits.
* The floor may be keyed ``floorLines`` or ``floorLine``; the
  first-player token is NOT a floor tile on the site — it is the
  ``hasFirstPlayerToken`` flag, which we translate into the
  ``FIRST_PLAYER`` sentinel on the floor.
* The site never reveals the bag or the lid. We put every unseen tile
  in the bag as a *supply estimate* (lid = 0): legal-move generation
  never consults the bag, and search rollouts only use it for
  determinized redeals, where an estimate is the best anyone can do.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from tiles.core import (
    CENTER,
    FIRST_PLAYER,
    NUM_COLORS,
    PHASE_DRAFTING,
    PHASE_GAME_OVER,
    Action,
    GameState,
    PlayerBoard,
    color_from_name,
    color_name,
)
from tiles.core.state import TILES_PER_COLOR, wall_bit

from .protocol import (
    choose_tiles_payload,
    is_first_player_tile,
    place_tiles_payload,
    tile_color_string,
)


def _tiles_to_counts(tiles: Any) -> List[int]:
    counts = [0] * NUM_COLORS
    if isinstance(tiles, list):
        for tile in tiles:
            name = tile_color_string(tile)
            if name is not None:
                try:
                    counts[color_from_name(name)] += 1
                except ValueError:
                    pass  # unknown color string; ignore defensively
    return counts


def _parse_pattern_lines(board: PlayerBoard, data: Any) -> None:
    lines = data.get("lines", []) if isinstance(data, dict) else (data or [])
    for row, cells in enumerate(lines[:5]):
        if not isinstance(cells, list):
            continue
        count = 0
        line_color = -1
        for cell in cells:
            if isinstance(cell, dict) and cell.get("selected"):
                name = tile_color_string(cell)
                if name is not None:
                    line_color = color_from_name(name)
                    count += 1
        if count:
            board.pattern_colors[row] = line_color
            board.pattern_counts[row] = min(count, row + 1)


def _parse_wall(board: PlayerBoard, data: Any) -> None:
    grid = data.get("grid", []) if isinstance(data, dict) else (data or [])
    for row, cells in enumerate(grid[:5]):
        if not isinstance(cells, list):
            continue
        for col, cell in enumerate(cells[:5]):
            selected = (
                cell.get("selected", False)
                if isinstance(cell, dict)
                else bool(cell)
            )
            if selected:
                board.wall |= wall_bit(row, col)


def _parse_player(name: str, pdata: Dict[str, Any]) -> PlayerBoard:
    board = PlayerBoard(name=name, score=int(pdata.get("score", 0) or 0))
    _parse_pattern_lines(board, pdata.get("patternLines"))
    _parse_wall(board, pdata.get("wall"))
    floor_data = pdata.get("floorLines") or pdata.get("floorLine") or []
    if isinstance(floor_data, list):
        for tile in floor_data:
            fname = tile_color_string(tile)
            if fname is not None:
                board.floor.append(color_from_name(fname))
    if pdata.get("hasFirstPlayerToken"):
        board.floor.append(FIRST_PLAYER)
    return board


def site_state_to_game_state(site_game: Dict[str, Any]) -> GameState:
    """Translate the site's authoritative ``game`` object into a
    ``tiles.core.GameState`` mirror."""
    players_dict = site_game.get("players", {}) or {}
    names = list(players_dict.keys())
    players = [_parse_player(name, players_dict[name] or {}) for name in names]

    factories = [
        _tiles_to_counts(f) for f in site_game.get("factories", []) or []
    ]
    center_raw = site_game.get("center", []) or []
    center = _tiles_to_counts(center_raw)
    center_has_fpt = any(is_first_player_tile(t) for t in center_raw)

    current_name = site_game.get("currentPlayer", "")
    current_player = names.index(current_name) if current_name in names else 0

    next_first = None
    for i, board in enumerate(players):
        if board.has_first_player_token():
            next_first = i
            break

    # Supply estimate: everything not visible on the table is "in the bag".
    visible = [0] * NUM_COLORS
    for counts in factories:
        for c in range(NUM_COLORS):
            visible[c] += counts[c]
    for c in range(NUM_COLORS):
        visible[c] += center[c]
    for board in players:
        for row in range(5):
            if board.pattern_colors[row] != -1:
                visible[board.pattern_colors[row]] += board.pattern_counts[row]
        for tile in board.floor:
            if tile != FIRST_PLAYER:
                visible[tile] += 1
        for row in range(5):
            for col in range(5):
                if board.wall_has(row, col):
                    visible[(col - row) % NUM_COLORS] += 1
    bag = [max(0, TILES_PER_COLOR - visible[c]) for c in range(NUM_COLORS)]

    return GameState(
        num_players=max(2, len(players)),
        factories=factories,
        center=center,
        center_has_fpt=center_has_fpt,
        bag=bag,
        lid=[0] * NUM_COLORS,
        players=players,
        current_player=current_player,
        round_number=int(site_game.get("round", 1) or 1),
        phase=(
            PHASE_GAME_OVER if site_game.get("gameOver") else PHASE_DRAFTING
        ),
        next_first_player=next_first,
    )


def action_to_site_moves(
    action: Action,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Translate a ``tiles.core.Action`` into the site's two-step
    ``(chooseTiles, placeTiles)`` payloads (room/player/gameName are
    seat-specific and added at emit time)."""
    choose = choose_tiles_payload(
        color_name(action.color),
        None if action.from_center else action.source_index,
    )
    place = place_tiles_payload(None if action.to_floor else action.dest_row)
    return choose, place


# ---------------------------------------------------------------------------
# Opponent action inference (for profiling human/remote players)
# ---------------------------------------------------------------------------


def infer_action(
    before: GameState, after: GameState, player_index: int
) -> Optional[Action]:
    """Best-effort reconstruction of the drafting action a player took,
    from two consecutive authoritative states. Returns None when the
    transition is not a plain drafting move (e.g. a round boundary)."""
    if player_index >= len(before.players) or player_index >= len(after.players):
        return None

    # Source: a factory that had tiles and is now empty, or the center.
    source_index: Optional[int] = None
    color: Optional[int] = None
    for i, (f_before, f_after) in enumerate(
        zip(before.factories, after.factories)
    ):
        if any(f_before) and not any(f_after):
            source_index = i
            break
    if source_index is None:
        # Center pick: some center color count dropped to zero.
        for c in range(NUM_COLORS):
            if before.center[c] > 0 and after.center[c] == 0:
                source_index = CENTER
                color = c
                break
        if source_index is None:
            return None
    else:
        # The chosen color is the one that did NOT land in the center.
        moved_to_center = [
            after.center[c] - before.center[c] for c in range(NUM_COLORS)
        ]
        candidates = [
            c
            for c in range(NUM_COLORS)
            if before.factories[source_index][c] > 0
            and moved_to_center[c] < before.factories[source_index][c]
        ]
        if len(candidates) != 1:
            # Ambiguous (shouldn't happen on a clean transition).
            if not candidates:
                return None
        color = candidates[0]

    board_before = before.players[player_index]
    board_after = after.players[player_index]
    dest_row = -1  # floor by default
    for row in range(5):
        if (
            board_after.pattern_counts[row] > board_before.pattern_counts[row]
            and board_after.pattern_colors[row] == color
        ):
            dest_row = row
            break
    return Action(source_index=source_index, color=color, dest_row=dest_row)
