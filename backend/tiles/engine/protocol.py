"""buddyboardgames.com Socket.IO protocol.

Everything TILES knows about the live platform's wire protocol lives
here, ported from the validated Milestone-1 implementation. No
Playwright imports — these are pure constants and payload builders so
they can be unit-tested and reused by any transport.

Wire format
-----------
The site speaks Socket.IO v4 over WebSocket. Event frames look like::

    42["eventName", {payload}]

Client -> server events (all sent as ``takeTurn`` variants except the
room/lobby ones handled by the site's own UI JS):

* ``joinRoom`` / ``createRoom`` — emitted by the site when the user
  fills ``#room`` and clicks ``#start-game``; first joiner creates the
  room and becomes host.
* ``startGame`` — emitted when the host clicks ``#start-game-lobby``.
* ``takeTurn`` — every in-game action. Common fields:
  ``{"room": ..., "player": ..., "gameName": "azul", "turnType": ...}``
  with turnType one of:

  - ``chooseTiles``: + ``tileType`` (color string) and either
    ``factory`` (stringified index) or ``center: true``.
  - ``placeTiles``: + either ``patternLine`` (stringified row 0-4) or
    ``floorLine: true``.
  - ``dealTiles``: no extra fields; the player whose turn it is must
    emit this to deal the next round's factories.

Server -> client events:

* ``joinRoomResponse`` ``{"success": bool, "player": name}``
* ``createRoomResponse`` — like joinRoomResponse, for the host.
* ``startGameResponse`` ``{"success": bool, "players": [player, ...]}``
* ``takeTurnResponse`` ``{"success": bool, "message"?: str,
  "game": {...}}`` — carries the FULL authoritative game state after
  every accepted turn (and a failure message after a rejected one).
* ``endGameResponse`` — final results.

The authoritative ``game`` object::

    {
      "room": str,
      "round": int,
      "currentPlayer": str,          # player NAME, not index
      "gameOver": bool,
      "factories": [[tile, ...], ...],   # tile = str | {"type"/"color": str}
      "center": [tile, ...],             # may include "firstPlayer"
      "players": {name: {
          "score": int,
          "patternLines": {"lines": [[cell x (row+1)] x 5]},
          #   cell = {"selected": bool, "color"/"type": str}
          #   row r has r+1 slots, same orientation as tiles.core
          "wall": {"grid": [[cell x 5] x 5]},
          #   positional; row 0 = blue yellow red black white (standard)
          "floorLine"/"floorLines": [tile, ...],
          "hasFirstPlayerToken": bool,
      }, ...}                            # dict order == seat order
    }

Tile color strings: ``black blue red white yellow`` plus the specials
``firstPlayer`` and ``dummy`` (placeholder tiles in the DOM).
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional, Tuple

GAME_NAME = "azul"
DEFAULT_PLATFORM_URL = "https://buddyboardgames.com/azul"

# Server -> client
EV_JOIN_ROOM_RESPONSE = "joinRoomResponse"
EV_CREATE_ROOM_RESPONSE = "createRoomResponse"
EV_START_GAME_RESPONSE = "startGameResponse"
EV_TAKE_TURN_RESPONSE = "takeTurnResponse"
EV_END_GAME_RESPONSE = "endGameResponse"

# Client -> server
EV_TAKE_TURN = "takeTurn"

TURN_CHOOSE = "chooseTiles"
TURN_PLACE = "placeTiles"
TURN_DEAL = "dealTiles"

SPECIAL_TILES = ("firstPlayer", "dummy")

# DOM selectors (join/lobby flow — the site has no join API, we drive
# its UI): see BrowserSeat.
SEL_ROOM_INPUT = "#room"
SEL_PLAY_BUTTON = "#start-game"
SEL_LOBBY_ROW = "#sharing-link-row"
SEL_START_LOBBY = "#start-game-lobby"


def parse_socketio_frame(raw: str) -> Optional[Tuple[str, Any]]:
    """Parse a raw Socket.IO WS frame into ``(event, payload)``.

    Only ``42[...]`` event frames are meaningful; pings/acks return None.
    """
    if not isinstance(raw, str) or not raw.startswith("42"):
        return None
    try:
        data = json.loads(raw[2:])
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, list) and len(data) >= 2:
        return data[0], data[1]
    return None


def tile_color_string(tile: Any) -> Optional[str]:
    """Extract the color string from the site's polymorphic tile
    representations (plain string, or dict keyed ``type``/``color``/
    ``tileColor`` depending on context). Returns None for specials."""
    if isinstance(tile, str):
        name = tile
    elif isinstance(tile, dict):
        name = tile.get("type") or tile.get("color") or tile.get("tileColor") or ""
    else:
        return None
    if not name or name in SPECIAL_TILES:
        return None
    return name


def is_first_player_tile(tile: Any) -> bool:
    if isinstance(tile, str):
        return tile == "firstPlayer"
    if isinstance(tile, dict):
        return (tile.get("type") or tile.get("color")) == "firstPlayer"
    return False


def base_turn_payload(room: str, player: str) -> Dict[str, Any]:
    return {"room": room, "player": player, "gameName": GAME_NAME}


def choose_tiles_payload(
    color_name: str, factory_index: Optional[int]
) -> Dict[str, Any]:
    """``chooseTiles`` payload (room/player/gameName added at emit time).

    ``factory_index=None`` means the center pool. The site expects the
    factory index as a *string*."""
    payload: Dict[str, Any] = {"turnType": TURN_CHOOSE, "tileType": color_name}
    if factory_index is None:
        payload["center"] = True
    else:
        payload["factory"] = str(factory_index)
    return payload


def place_tiles_payload(dest_row: Optional[int]) -> Dict[str, Any]:
    """``placeTiles`` payload. ``dest_row=None`` means the floor line.
    The site expects the pattern row as a *string*."""
    payload: Dict[str, Any] = {"turnType": TURN_PLACE}
    if dest_row is None:
        payload["floorLine"] = True
    else:
        payload["patternLine"] = str(dest_row)
    return payload


def deal_tiles_payload() -> Dict[str, Any]:
    return {"turnType": TURN_DEAL}
