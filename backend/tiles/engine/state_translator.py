"""Translate between the site's authoritative game object and tiles.core.

Mapping notes (verified live, October 2026; the 2025 shapes from the
Milestone-1 parser are still accepted):

* Seat order comes from ``game.playerOrder`` (fallback: insertion order
  of the ``game.players`` dict). The player to move is
  ``playerOrder[playerTurnIndex]`` (fallback: the legacy
  ``currentPlayer`` NAME).
* The center pool is ``centerTiles`` (legacy ``center``); the
  first-player token sits in it as ``{"type": "firstPlayer"}``.
* Pattern lines arrive as ``{"lines": [[cell x (row+1)] x 5]}`` with row
  0 holding one slot — the same orientation as ``tiles.core``. A cell is
  ``{"selected": bool, "value": {"type": color}}`` (legacy
  ``"color"``/``"type"`` keys); unselected cells are empty slots.
* The wall arrives as ``{"rows": ...}`` (legacy ``{"grid": ...}``), a
  positional 5x5 in the standard Azul orientation (row 0 = blue yellow
  red black white), which matches ``tiles.core.wall_color_at`` exactly,
  so ``selected`` flags map 1:1 onto wall bits.
* The floor is ``floorLines: {"lines": [cell x 7]}`` (legacy: a flat
  ``floorLine``/``floorLines`` list of tiles). The first-player token is
  reported through ``hasFirstPlayerToken``, which we translate into the
  ``FIRST_PLAYER`` sentinel on the floor (once).
* The site does not number rounds or flag game over in the game object.
  Callers pass ``round_number`` (the seat counts ``dealTiles`` responses)
  and game over is derived: a completed wall row while no round is in
  progress, or any explicit ``gameOver``-style flag.
* The bag is reported (``tileBag``) and so is the lid
  (``discardedTiles``); when absent we fall back to a supply estimate
  (every unseen tile in the bag), which only matters for determinized
  redeals inside search.
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

_GAME_OVER_FLAGS = ("gameOver", "isGameOver", "gameFinished", "gameEnded")


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


def _cells(data: Any, key: str) -> list:
    """``{"lines": [...]}`` / ``{"rows": [...]}`` / ``{"grid": [...]}`` or a bare list."""
    if isinstance(data, dict):
        for k in (key, "lines", "rows", "grid"):
            if isinstance(data.get(k), list):
                return data[k]
        return []
    return data if isinstance(data, list) else []


def _parse_pattern_lines(board: PlayerBoard, data: Any) -> None:
    for row, cells in enumerate(_cells(data, "lines")[:5]):
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
    for row, cells in enumerate(_cells(data, "rows")[:5]):
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


def _parse_floor(board: PlayerBoard, data: Any) -> bool:
    """Append floor tiles; returns True if the token was found there."""
    token = False
    for tile in _cells(data, "lines"):
        if isinstance(tile, dict) and "selected" in tile and not tile.get("selected"):
            continue  # empty floor slot
        if is_first_player_tile(tile):
            token = True
            continue
        fname = tile_color_string(tile)
        if fname is not None:
            board.floor.append(color_from_name(fname))
    return token


def _parse_player(name: str, pdata: Dict[str, Any]) -> PlayerBoard:
    board = PlayerBoard(name=name, score=int(pdata.get("score", 0) or 0))
    _parse_pattern_lines(board, pdata.get("patternLines"))
    _parse_wall(board, pdata.get("wall"))
    token_on_floor = _parse_floor(
        board, pdata.get("floorLines") if pdata.get("floorLines") is not None else pdata.get("floorLine")
    )
    if pdata.get("hasFirstPlayerToken") or token_on_floor:
        board.floor.append(FIRST_PLAYER)
    return board


def _seat_order(site_game: Dict[str, Any], players_dict: Dict[str, Any]) -> List[str]:
    order = site_game.get("playerOrder")
    if isinstance(order, list) and order and all(n in players_dict for n in order):
        names = [n for n in order]
        names += [n for n in players_dict if n not in names]
        return names
    return list(players_dict.keys())


def current_player_name(site_game: Dict[str, Any]) -> str:
    """Name of the player to move, from either protocol generation."""
    players_dict = site_game.get("players", {}) or {}
    names = _seat_order(site_game, players_dict)
    idx = site_game.get("playerTurnIndex")
    if isinstance(idx, int) and 0 <= idx < len(names):
        return names[idx]
    name = site_game.get("currentPlayer", "")
    return name if isinstance(name, str) else ""


def _derive_game_over(site_game: Dict[str, Any], players: List[PlayerBoard]) -> bool:
    if any(site_game.get(flag) for flag in _GAME_OVER_FLAGS):
        return True
    if site_game.get("roundInProgress") is False and site_game.get("gameStarted") is True:
        return any(p.completed_rows() > 0 for p in players)
    return False


def site_state_to_game_state(
    site_game: Dict[str, Any], round_number: Optional[int] = None
) -> GameState:
    """Translate the site's authoritative ``game`` object into a
    ``tiles.core.GameState`` mirror."""
    players_dict = site_game.get("players", {}) or {}
    names = _seat_order(site_game, players_dict)
    players = [_parse_player(name, players_dict[name] or {}) for name in names]

    factories = [
        _tiles_to_counts(f) for f in site_game.get("factories", []) or []
    ]
    center_raw = site_game.get("centerTiles")
    if center_raw is None:
        center_raw = site_game.get("center", []) or []
    center = _tiles_to_counts(center_raw)
    center_has_fpt = any(is_first_player_tile(t) for t in center_raw)

    current_name = current_player_name(site_game)
    current_player = names.index(current_name) if current_name in names else 0

    next_first = None
    for i, board in enumerate(players):
        if board.has_first_player_token():
            next_first = i
            break

    if isinstance(site_game.get("tileBag"), list):
        bag = _tiles_to_counts(site_game["tileBag"])
        lid = _tiles_to_counts(site_game.get("discardedTiles") or [])
    else:
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
        lid = [0] * NUM_COLORS

    if round_number is None:
        round_number = int(site_game.get("round", 1) or 1)
    game_over = _derive_game_over(site_game, players)

    return GameState(
        num_players=max(2, len(players)),
        factories=factories,
        center=center,
        center_has_fpt=center_has_fpt,
        bag=bag,
        lid=lid,
        players=players,
        current_player=current_player,
        round_number=max(1, int(round_number)),
        phase=PHASE_GAME_OVER if game_over else PHASE_DRAFTING,
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


def _drafting_signature(state: GameState) -> tuple:
    """The parts of a state a single drafting move changes."""
    return (
        tuple(tuple(f) for f in state.factories),
        tuple(state.center),
        state.center_has_fpt,
        tuple(_board_signature(b) + (tuple(sorted(b.floor)),) for b in state.players),
    )


def _tiled_signature(state: GameState) -> tuple:
    """What wall-tiling leaves behind: walls and unfinished pattern lines
    (the table may already be redealt, so it is ignored)."""
    return tuple(_board_signature(b) for b in state.players)


def _board_signature(board: PlayerBoard) -> tuple:
    return (
        board.wall,
        tuple(
            (board.pattern_counts[r], board.pattern_colors[r] if board.pattern_counts[r] else -1)
            for r in range(5)
        ),
    )


def infer_action(
    before: GameState, after: GameState, player_index: int
) -> Optional[Action]:
    """Reconstruct the drafting action ``player_index`` took between two
    consecutive authoritative states, or None if no legal move explains
    the change (no move, a missed frame, or a pure redeal).

    Every legal move is simulated and matched against ``after``, so the
    result is always legal. A round-ending move is matched after
    wall-tiling, because the platform shows that board already tiled.
    """
    from tiles.core import apply_action, legal_actions, resolve_round

    if player_index >= len(before.players) or player_index >= len(after.players):
        return None
    probe = before.clone()
    probe.current_player = player_index
    candidates = legal_actions(probe)

    target = _drafting_signature(after)
    if target == _drafting_signature(before):
        return None  # the same frame again: nothing was played
    tiled_target = _tiled_signature(after)
    tiled_matches: List[Tuple[Action, bool]] = []
    for action in candidates:
        sim = probe.clone()
        try:
            apply_action(sim, action)
        except ValueError:
            continue
        if _drafting_signature(sim) == target:
            return action
        if sim.drafting_exhausted():
            resolve_round(sim)
            if _tiled_signature(sim) == tiled_target:
                tiled_matches.append((action, sim.scores() == after.scores()))
    if not tiled_matches:
        return None
    # Prefer the candidate whose scoring also agrees with the platform.
    return next((a for a, scored in tiled_matches if scored), tiled_matches[0][0])


# ---------------------------------------------------------------------------
# GameState -> site game (the inverse mapping; used by the offline live-loop
# harness and by anyone who wants to render a local state the site's way)
# ---------------------------------------------------------------------------


def game_state_to_site_game(state: GameState, room: str = "local") -> Dict[str, Any]:
    """Serialize a ``GameState`` as the site's current ``game`` object.

    ``site_state_to_game_state(game_state_to_site_game(s), s.round_number)``
    reproduces ``s`` up to ``next_first_player``.
    """
    from tiles.core import COLOR_NAMES, wall_color_at

    def tiles(counts: List[int]) -> List[Dict[str, str]]:
        return [
            {"type": COLOR_NAMES[color]}
            for color in range(NUM_COLORS)
            for _ in range(counts[color])
        ]

    players: Dict[str, Dict[str, Any]] = {}
    for board in state.players:
        lines = []
        for row in range(5):
            cells = []
            for i in range(row + 1):
                if i < board.pattern_counts[row]:
                    cells.append(
                        {"selected": True, "value": {"type": COLOR_NAMES[board.pattern_colors[row]]}}
                    )
                else:
                    cells.append({"selected": False})
            lines.append(cells)
        rows = [
            [
                {"selected": board.wall_has(r, c), "value": {"type": COLOR_NAMES[wall_color_at(r, c)]}}
                for c in range(5)
            ]
            for r in range(5)
        ]
        floor_tiles = [t for t in board.floor if t != FIRST_PLAYER]
        floor_cells = []
        for i in range(7):
            if i < len(floor_tiles):
                floor_cells.append({"selected": True, "penalty": -1, "value": {"type": COLOR_NAMES[floor_tiles[i]]}})
            else:
                floor_cells.append({"selected": False, "penalty": -1})
        players[board.name] = {
            "name": board.name,
            "score": board.score,
            "patternLines": {"lines": lines},
            "wall": {"rows": rows},
            "floorLines": {"lines": floor_cells},
            "hasFirstPlayerToken": board.has_first_player_token(),
        }

    center: List[Any] = tiles(state.center)
    if state.center_has_fpt:
        center.append({"type": "firstPlayer"})
    return {
        "room": room,
        "gameStarted": True,
        "roundInProgress": not state.is_game_over,
        "playerOrder": [p.name for p in state.players],
        "playerTurnIndex": state.current_player,
        "gameOver": state.is_game_over,
        "factories": [tiles(f) for f in state.factories],
        "centerTiles": center,
        "tileBag": tiles(state.bag),
        "discardedTiles": tiles(state.lid),
        "players": players,
    }
