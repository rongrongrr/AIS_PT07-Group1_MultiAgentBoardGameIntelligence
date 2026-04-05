"""Parse Azul game state from Socket.IO events or DOM scraping."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.schemas import GameStateData, PlayerState, TileColor

logger = logging.getLogger(__name__)

# Wall color order per row (standard Azul pattern)
WALL_COLORS = [
    ["blue", "yellow", "red", "black", "white"],
    ["white", "blue", "yellow", "red", "black"],
    ["black", "white", "blue", "yellow", "red"],
    ["red", "black", "white", "blue", "yellow"],
    ["yellow", "red", "black", "white", "blue"],
]


def parse_socketio_message(raw: str) -> Optional[tuple]:
    """Parse a raw Socket.IO message into (event_name, payload).

    Socket.IO v4 messages are formatted as: 42["eventName", {payload}]
    """
    if not raw.startswith("42"):
        return None
    try:
        data = json.loads(raw[2:])
        if isinstance(data, list) and len(data) >= 2:
            return data[0], data[1]
    except (json.JSONDecodeError, IndexError):
        pass
    return None


def parse_game_state_from_event(payload: Dict[str, Any], session_id: str = "") -> Optional[GameStateData]:
    """Parse a takeTurnResponse payload into a GameStateData.

    The payload structure from buddyboardgames:
    {
        "success": true,
        "game": {
            "room": "...",
            "players": { "name1": {...}, "name2": {...} },
            "factories": [[...], ...],
            "center": [...],
            "currentPlayer": "name",
            "round": 1,
            "gameOver": false,
            ...
        }
    }
    """
    if not payload.get("success"):
        return None

    game = payload.get("game")
    if not game:
        return None

    return _parse_game_object(game, session_id)


def parse_start_game_response(payload: Dict[str, Any], room_name: str, session_id: str = "") -> Optional[GameStateData]:
    """Parse a startGameResponse into initial GameStateData."""
    if not payload.get("success"):
        return None

    players_data = payload.get("players", [])
    players = []
    for i, p in enumerate(players_data):
        players.append(_parse_player_from_start(p, i))

    return GameStateData(
        timestamp=datetime.utcnow(),
        session_id=session_id,
        room_name=room_name,
        round=1,
        current_turn=players[0].name if players else "",
        factories=[],
        center_pool=[],
        players=players,
        game_over=False,
    )


def _parse_game_object(game: Dict[str, Any], session_id: str) -> GameStateData:
    """Parse the full game object from takeTurnResponse."""
    players_dict = game.get("players", {})
    players = []

    # Determine player order from the server data
    for i, (name, pdata) in enumerate(players_dict.items()):
        players.append(_parse_player_from_turn(pdata, name, i))

    # Parse factories
    factories = []
    for factory_data in game.get("factories", []):
        factory_tiles = []
        for tile in factory_data:
            color = _extract_tile_color(tile)
            if color:
                factory_tiles.append(color)
        factories.append(factory_tiles)

    # Parse center pool
    center = []
    for tile in game.get("center", []):
        if isinstance(tile, str):
            center.append(tile)
        elif isinstance(tile, dict):
            color = tile.get("type") or tile.get("color") or tile.get("tileColor") or ""
            if color:
                center.append(color)

    return GameStateData(
        timestamp=datetime.utcnow(),
        session_id=session_id,
        room_name=game.get("room", ""),
        round=game.get("round", 1),
        current_turn=game.get("currentPlayer", ""),
        factories=factories,
        center_pool=center,
        players=players,
        game_over=game.get("gameOver", False),
    )


def _parse_player_from_turn(pdata: Dict[str, Any], name: str, index: int) -> PlayerState:
    """Parse a player from the takeTurnResponse game.players dict."""
    # Pattern lines
    pattern_lines = _parse_pattern_lines(pdata.get("patternLines", {}))

    # Wall
    wall = _parse_wall(pdata.get("wall", {}))

    # Floor — server uses "floorLines" (plural) or "floorLine"
    floor_line = _parse_floor(
        pdata.get("floorLines") or pdata.get("floorLine") or []
    )

    return PlayerState(
        index=index,
        name=name,
        system_tag=None,
        score=pdata.get("score", 0),
        pattern_lines=pattern_lines,
        wall=wall,
        floor_line=floor_line,
        has_first_player_token=pdata.get("hasFirstPlayerToken", False),
    )


def _parse_player_from_start(pdata: Dict[str, Any], index: int) -> PlayerState:
    """Parse a player from startGameResponse players list."""
    pattern_lines = _parse_pattern_lines(pdata.get("patternLines", {}))
    wall = _parse_wall(pdata.get("wall", {}))
    floor_line = _parse_floor(
        pdata.get("floorLines") or pdata.get("floorLine") or []
    )

    return PlayerState(
        index=index,
        name=pdata.get("name", f"Player_{index}"),
        system_tag=None,
        score=pdata.get("score", 0),
        pattern_lines=pattern_lines,
        wall=wall,
        floor_line=floor_line,
        has_first_player_token=False,
    )


def _parse_pattern_lines(pl_data: Any) -> List[List[Optional[TileColor]]]:
    """Parse pattern lines from server format.

    Server format: {"lines": [[{"selected": bool, "color": str}, ...], ...]}
    """
    result = [[] for _ in range(5)]

    if isinstance(pl_data, dict):
        lines = pl_data.get("lines", [])
    elif isinstance(pl_data, list):
        lines = pl_data
    else:
        return result

    for row_idx, row in enumerate(lines):
        if row_idx >= 5:
            break
        row_tiles = []
        if isinstance(row, list):
            for cell in row:
                if isinstance(cell, dict) and cell.get("selected"):
                    color_str = cell.get("type") or cell.get("color") or ""
                    color = _safe_tile_color(color_str)
                    row_tiles.append(color)
                # If not selected, it's an empty slot — don't append
        result[row_idx] = row_tiles

    return result


def _parse_wall(wall_data: Any) -> List[List[bool]]:
    """Parse wall from server format.

    Server format: {"grid": [[{"selected": bool, "color": str}, ...], ...]}
    """
    result = [[False] * 5 for _ in range(5)]

    if isinstance(wall_data, dict):
        grid = wall_data.get("grid", [])
    elif isinstance(wall_data, list):
        grid = wall_data
    else:
        return result

    for row_idx, row in enumerate(grid):
        if row_idx >= 5:
            break
        if isinstance(row, list):
            for col_idx, cell in enumerate(row):
                if col_idx >= 5:
                    break
                if isinstance(cell, dict):
                    result[row_idx][col_idx] = cell.get("selected", False)
                elif isinstance(cell, bool):
                    result[row_idx][col_idx] = cell

    return result


def _parse_floor(floor_data: Any) -> List[TileColor]:
    """Parse floor line from server format."""
    result = []
    if not isinstance(floor_data, list):
        return result
    for tile in floor_data:
        if isinstance(tile, dict):
            color_str = tile.get("type") or tile.get("color") or ""
        elif isinstance(tile, str):
            color_str = tile
        else:
            continue
        color = _safe_tile_color(color_str)
        if color:
            result.append(color)
    return result


def _extract_tile_color(tile: Any) -> Optional[TileColor]:
    """Extract a TileColor from various tile representations.

    The platform uses different key names in different contexts:
    - factories: {"type": "red"}
    - pattern lines: {"color": "red", "selected": true}
    - center: {"type": "red"} or "firstPlayer"
    """
    if isinstance(tile, str):
        return _safe_tile_color(tile)
    if isinstance(tile, dict):
        # Try all known key names
        color_str = (
            tile.get("type")
            or tile.get("color")
            or tile.get("tileColor")
            or ""
        )
        return _safe_tile_color(color_str)
    return None


def _safe_tile_color(color_str: str) -> Optional[TileColor]:
    """Safely convert a string to TileColor, returning None for invalid/special values."""
    if not color_str or color_str in ("firstPlayer", "dummy", ""):
        return None
    try:
        return TileColor(color_str)
    except ValueError:
        logger.warning(f"Unknown tile color: {color_str}")
        return None


async def parse_state_from_dom(page) -> Optional[GameStateData]:
    """Fallback: Parse game state directly from the DOM using Playwright page.

    This is less reliable than intercepting Socket.IO events but serves as a
    fallback if event interception fails.
    """
    try:
        state_data = await page.evaluate("""() => {
            const state = {factories: [], center: [], players: []};

            // Parse factories — preserve index alignment with DOM IDs
            const factoryEls = document.querySelectorAll('.factory');
            factoryEls.forEach((f, fi) => {
                const tiles = [];
                f.querySelectorAll('.tile').forEach(t => {
                    const color = t.getAttribute('tilecolor');
                    if (color && color !== 'dummy') tiles.push(color);
                });
                // Always push (even if empty) to keep indices aligned with DOM #factory-N
                state.factories.push(tiles);
            });

            // Parse center
            const centerRow = document.querySelector('#center-row');
            if (centerRow) {
                centerRow.querySelectorAll('.tile').forEach(t => {
                    const color = t.getAttribute('tilecolor');
                    if (color) state.center.push(color);
                });
            }

            // Parse my board (player 0)
            const myScore = document.querySelector('#player-0-score');
            const myName = document.querySelector('#me-info-name');
            const myPlayer = {
                name: myName ? myName.textContent.trim() : 'Unknown',
                score: myScore ? parseInt(myScore.textContent) || 0 : 0,
                patternLines: [],
                wall: [],
                floorLine: [],
            };

            // Pattern lines
            for (let row = 0; row < 5; row++) {
                const rowTiles = [];
                for (let col = 0; col <= row; col++) {
                    const el = document.querySelector(
                        `#player-0-pattern-line-row-${row}-col-${col}`
                    );
                    if (el && el.classList.contains('selected')) {
                        const color = Array.from(el.classList).find(
                            c => ['blue','yellow','red','black','white'].includes(c)
                        );
                        if (color) rowTiles.push(color);
                    }
                }
                myPlayer.patternLines.push(rowTiles);
            }

            // Wall
            const wallColors = [
                ['blue','yellow','red','black','white'],
                ['white','blue','yellow','red','black'],
                ['black','white','blue','yellow','red'],
                ['red','black','white','blue','yellow'],
                ['yellow','red','black','white','blue'],
            ];
            for (let row = 0; row < 5; row++) {
                const wallRow = [];
                for (const color of wallColors[row]) {
                    const el = document.querySelector(
                        `#player-0-wall-row-${row}-color-${color}`
                    );
                    wallRow.push(el ? el.classList.contains('selected') : false);
                }
                myPlayer.wall.push(wallRow);
            }

            // Floor
            for (let i = 0; i < 7; i++) {
                const el = document.querySelector(`#player-0-floor-tile-${i}`);
                if (el) {
                    const color = el.getAttribute('tilecolor');
                    if (color && color !== 'dummy') myPlayer.floorLine.push(color);
                }
            }

            state.players.push(myPlayer);

            // Parse other players
            for (let p = 1; p < 4; p++) {
                const scoreEl = document.querySelector(`#player-${p}-score`);
                if (!scoreEl) break;
                // Try to read name from the other-player info section
                const otherInfos = document.querySelectorAll('.other-player-info-text b, .other-player-info-text strong');
                const nameFromDOM = otherInfos[p - 1]?.textContent?.trim();
                // Also try avatar title or nearby name element
                const avatarName = document.querySelector(`#avatar-player-${p}`)?.parentElement?.querySelector('b, strong')?.textContent?.trim();
                const otherPlayer = {
                    name: nameFromDOM || avatarName || `Player_${p}`,
                    score: parseInt(scoreEl.textContent) || 0,
                    patternLines: [],
                    wall: [],
                    floorLine: [],
                };
                // Other players pattern lines and wall follow same structure
                for (let row = 0; row < 5; row++) {
                    const rowTiles = [];
                    for (let col = 0; col <= row; col++) {
                        const el = document.querySelector(
                            `#player-${p}-pattern-line-row-${row}-col-${col}`
                        );
                        if (el && el.classList.contains('selected')) {
                            const color = Array.from(el.classList).find(
                                c => ['blue','yellow','red','black','white'].includes(c)
                            );
                            if (color) rowTiles.push(color);
                        }
                    }
                    otherPlayer.patternLines.push(rowTiles);
                }
                for (let row = 0; row < 5; row++) {
                    const wallRow = [];
                    for (const color of wallColors[row]) {
                        const el = document.querySelector(
                            `#player-${p}-wall-row-${row}-color-${color}`
                        );
                        wallRow.push(
                            el ? el.classList.contains('selected') : false
                        );
                    }
                    otherPlayer.wall.push(wallRow);
                }
                state.players.push(otherPlayer);
            }

            return state;
        }""")

        # Convert DOM data to GameStateData
        players = []
        for i, p in enumerate(state_data.get("players", [])):
            pattern_lines = []
            for row_tiles in p.get("patternLines", []):
                pattern_lines.append(
                    [_safe_tile_color(c) for c in row_tiles if _safe_tile_color(c)]
                )
            while len(pattern_lines) < 5:
                pattern_lines.append([])

            wall = p.get("wall", [[False] * 5 for _ in range(5)])
            floor = [
                _safe_tile_color(c)
                for c in p.get("floorLine", [])
                if _safe_tile_color(c)
            ]

            players.append(PlayerState(
                index=i,
                name=p.get("name", f"Player_{i}"),
                score=p.get("score", 0),
                pattern_lines=pattern_lines,
                wall=wall,
                floor_line=floor,
            ))

        factories = []
        for f in state_data.get("factories", []):
            factory_tiles = [_safe_tile_color(c) for c in f if _safe_tile_color(c)]
            factories.append(factory_tiles)

        center = state_data.get("center", [])

        return GameStateData(
            timestamp=datetime.utcnow(),
            factories=factories,
            center_pool=center,
            players=players,
        )

    except Exception as e:
        logger.error(f"DOM parsing failed: {e}")
        return None
