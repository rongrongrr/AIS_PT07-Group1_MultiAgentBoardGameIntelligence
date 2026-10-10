"""buddyboardgames.com wire protocol.

Everything TILES knows about the live platform's protocol lives here —
pure constants, parsers and payload builders with no Playwright
imports, so they can be unit-tested and reused by any transport.

Wire format (verified live, October 2026)
-----------------------------------------
The site opens one plain WebSocket per page::

    wss://buddyboardgames.com/do-ws?game=azul&room=<room>

and exchanges JSON frames of the form ``{"type": <event>, "payload": {...}}``
plus bare ``ping``/``pong`` keep-alives. (Milestone 1 documented the
previous Socket.IO transport, ``42["event", {...}]`` on ``/socket.io/``;
``parse_frame`` still understands it so old recordings replay.)

Client -> server events:

* ``joinRoom`` ``{room, player, gameName: "azul", buddy}`` — emitted by
  the site's own UI when the user fills ``#room`` and clicks
  ``#start-game``. If the room does not exist the server answers
  ``success: false`` and the client follows up with ``createRoom`` (the
  first joiner becomes host).
* ``startGame`` ``{room, player}`` — host clicks ``#start-game-lobby``.
  The host's client then emits the opening ``dealTiles`` itself.
* ``takeTurn`` — every in-game action. Common fields:
  ``{room, player, gameName: "azul", turnType}`` with turnType one of:

  - ``chooseTiles``: + ``tileType`` (color string) and either
    ``factory`` (stringified index) or ``center: true``.
  - ``placeTiles``: + either ``patternLine`` (stringified row 0-4) or
    ``floorLine: true``.
  - ``dealTiles``: no extra fields; the player whose turn it is deals
    the next round's factories (the site's client normally does this
    on its own).

Server -> client events:

* ``joinRoomResponse`` ``{success, message, players: [names...],
  playersData, roomHost, isHost}`` — sent to the joiner, and to
  everyone already in the room (then listing only the new joiner).
* ``createRoomResponse`` ``{success, roomHost, players, minPlayers,
  maxPlayers, ...}`` — to the host.
* ``startGameResponse`` ``{success, players: [player objects in seat
  order]}``.
* ``takeTurnResponse`` ``{success, message?, turnType, player,
  playerTurn, isRoundOver?, game: {...}}`` — carries the FULL
  authoritative game state after every accepted turn (and a failure
  message after a rejected one).
* ``emoteResponse`` — chat emotes; ignored.

The authoritative ``game`` object::

    {
      "room": str, "round": int, "currentPlayer": str (player NAME),
      "gameOver": bool,
      "factories": [[{"type": color}, ...], ...],
      "center": [{"type": color} | "firstPlayer", ...],
      "players": {name: {                 # dict order == seat order
          "score": int,
          "patternLines": {"lines": [[cell x (row+1)] x 5]},
          "wall": {"rows": [[cell x 5] x 5]},      # was "grid" in 2025
          "floorLines": {"lines": [cell x 7]},     # was a flat list
          "hasFirstPlayerToken": bool, ...
      }, ...}
    }

where a cell is ``{"selected": bool, "value": {"type": color}}`` (the
older ``"color"``/``"type"`` keys are still accepted by the translator).
Tile color strings: ``black blue red white yellow`` plus the specials
``firstPlayer`` and ``dummy`` (placeholder tiles in the DOM).

Joining as a human: open ``room_link(...)`` — ``?room=<base64 room>``
pre-fills the room field (``?name=<base64 name>`` pre-fills the name);
then click *Play*. The site only accepts base64 for these parameters.
"""

from __future__ import annotations

import json
from base64 import b64encode
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
SEL_NAME_INPUT = "#player"
SEL_ROOM_INPUT = "#room"
SEL_PLAY_BUTTON = "#start-game"
SEL_LOBBY_ROW = "#sharing-link-row"
SEL_START_LOBBY = "#start-game-lobby"


def b64(text: str) -> str:
    return b64encode(text.encode("utf-8")).decode("ascii")


def seat_url(platform_url: str, player_name: str) -> str:
    """Page URL for a bot seat (name pre-filled; the seat types the room)."""
    return f"{platform_url}?name={b64(player_name)}"


def room_link(platform_url: str, room_name: str, player_name: Optional[str] = None) -> str:
    """Share link for humans: room (and optionally name) pre-filled."""
    link = f"{platform_url}?room={b64(room_name)}"
    if player_name:
        link += f"&name={b64(player_name)}"
    return link


def parse_frame(raw: Any) -> Optional[Tuple[str, Any]]:
    """Parse a raw WS frame into ``(event, payload)``.

    Understands the current ``{"type": ..., "payload": ...}`` JSON frames
    and the legacy Socket.IO ``42["event", payload]`` frames. Keep-alives
    (``ping``/``pong``), acks and anything unparsable return None.
    """
    if not isinstance(raw, str) or not raw:
        return None
    if raw.startswith("42"):
        try:
            data = json.loads(raw[2:])
        except (json.JSONDecodeError, ValueError):
            return None
        if isinstance(data, list) and len(data) >= 2:
            return data[0], data[1]
        return None
    if raw[0] != "{":
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, dict) and isinstance(data.get("type"), str):
        return data["type"], data.get("payload")
    return None


#: Backwards-compatible alias (Milestone-1 name).
parse_socketio_frame = parse_frame


def tile_color_string(tile: Any) -> Optional[str]:
    """Extract the color string from the site's polymorphic tile
    representations: a plain string, a dict keyed ``type``/``color``/
    ``tileColor``, or a cell wrapping one under ``value``. Returns None
    for specials and empties."""
    if isinstance(tile, str):
        name = tile
    elif isinstance(tile, dict):
        name = tile.get("type") or tile.get("color") or tile.get("tileColor") or ""
        if not name and isinstance(tile.get("value"), (dict, str)):
            return tile_color_string(tile["value"])
    else:
        return None
    if not name or name in SPECIAL_TILES:
        return None
    return name


def is_first_player_tile(tile: Any) -> bool:
    if isinstance(tile, str):
        return tile == "firstPlayer"
    if isinstance(tile, dict):
        if (tile.get("type") or tile.get("color")) == "firstPlayer":
            return True
        return is_first_player_tile(tile.get("value"))
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


def frame(event: str, payload: Dict[str, Any]) -> str:
    """Serialize a client -> server frame."""
    return json.dumps({"type": event, "payload": payload})
