"""DOM fallback: read the board straight off the page.

The authoritative game object normally arrives in every
``takeTurnResponse`` frame, but right after ``startGame`` (before the
first deal) or after a dropped frame there may be none. This module
scrapes the same board from the DOM — selectors mapped in the
Milestone-1 exploration (``#factory-N-tile-M[tilecolor]``,
``#player-P-pattern-line-row-R-col-C.selected``,
``#player-P-wall-row-R-color-{color}.selected``,
``#player-P-floor-tile-N[tilecolor]``, ``#player-P-score``) — and shapes
it like the site's ``game`` object so ``state_translator`` can consume
it unchanged.

Only the local player's board carries the ``.current-turn`` marker in the
DOM, so ``currentPlayer`` is filled in only when it is this seat's turn.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .protocol import SPECIAL_TILES

WALL_COLORS = [
    ["blue", "yellow", "red", "black", "white"],
    ["white", "blue", "yellow", "red", "black"],
    ["black", "white", "blue", "yellow", "red"],
    ["red", "black", "white", "blue", "yellow"],
    ["yellow", "red", "black", "white", "blue"],
]

#: page.evaluate() payload → raw snapshot (see ``snapshot_to_site_game``)
DOM_SNAPSHOT_JS = """
() => {
    const colors = ['blue','yellow','red','black','white'];
    const wallColors = [
        ['blue','yellow','red','black','white'],
        ['white','blue','yellow','red','black'],
        ['black','white','blue','yellow','red'],
        ['red','black','white','blue','yellow'],
        ['yellow','red','black','white','blue'],
    ];
    const tileColor = (el) => el ? el.getAttribute('tilecolor') : null;
    const snap = {factories: [], center: [], players: [], myTurn: false};

    document.querySelectorAll('.factory').forEach((f) => {
        const tiles = [];
        f.querySelectorAll('.tile[tilecolor]').forEach((t) => {
            const c = tileColor(t);
            if (c && c !== 'dummy') tiles.push(c);
        });
        snap.factories.push(tiles);
    });
    const center = document.querySelector('#center-row');
    if (center) {
        center.querySelectorAll('.tile[tilecolor]').forEach((t) => {
            const c = tileColor(t);
            if (c && c !== 'dummy') snap.center.push(c);
        });
    }
    const readBoard = (p) => {
        const patternLines = [];
        for (let row = 0; row < 5; row++) {
            const cells = [];
            for (let col = 0; col <= row; col++) {
                const el = document.querySelector(
                    `#player-${p}-pattern-line-row-${row}-col-${col}`);
                const selected = !!(el && el.classList.contains('selected'));
                const color = selected
                    ? colors.find((c) => el.classList.contains(c)) || null
                    : null;
                cells.push({selected: selected && !!color, color: color});
            }
            patternLines.push(cells);
        }
        const wall = [];
        for (let row = 0; row < 5; row++) {
            const cells = [];
            for (const color of wallColors[row]) {
                const el = document.querySelector(
                    `#player-${p}-wall-row-${row}-color-${color}`);
                cells.push({selected: !!(el && el.classList.contains('selected')),
                            color: color});
            }
            wall.push(cells);
        }
        const floor = [];
        for (let i = 0; i < 7; i++) {
            const c = tileColor(document.querySelector(`#player-${p}-floor-tile-${i}`));
            if (c && c !== 'dummy') floor.push(c);
        }
        return {patternLines: patternLines, wall: wall, floorLine: floor};
    };

    const myScore = document.querySelector('#player-0-score');
    const myName = document.querySelector('#me-info-name');
    const meInfo = document.querySelector('#me-info');
    snap.myTurn = !!(meInfo && meInfo.classList.contains('current-turn'));
    snap.players.push(Object.assign({
        name: myName ? myName.textContent.trim() : '',
        score: myScore ? parseInt(myScore.textContent) || 0 : 0,
    }, readBoard(0)));
    const otherNames = Array.from(document.querySelectorAll(
        '.other-player-info-text b, .other-player-info-text strong'))
        .map((el) => el.textContent.trim());
    for (let p = 1; p < 4; p++) {
        const scoreEl = document.querySelector(`#player-${p}-score`);
        if (!scoreEl) break;
        snap.players.push(Object.assign({
            name: otherNames[p - 1] || `Player_${p}`,
            score: parseInt(scoreEl.textContent) || 0,
        }, readBoard(p)));
    }
    return snap;
}
"""


def _tile_list(colors: List[str]) -> List[Dict[str, str]]:
    return [{"type": c} for c in colors if c and c not in SPECIAL_TILES]


def snapshot_to_site_game(
    snapshot: Dict[str, Any],
    seat_name: str,
    seat_order: Optional[List[str]] = None,
    round_number: int = 1,
) -> Optional[Dict[str, Any]]:
    """Shape a raw DOM snapshot like the site's authoritative ``game``.

    ``seat_order`` (names as listed by ``startGameResponse``) fixes the
    player order; the DOM always lists the local player first. Returns
    None when the snapshot is unusable (no players or no board).
    """
    players_raw = snapshot.get("players") or []
    if not players_raw:
        return None
    players: Dict[str, Dict[str, Any]] = {}
    for p in players_raw:
        name = p.get("name") or seat_name
        players[name] = {
            "score": int(p.get("score", 0) or 0),
            "patternLines": {"lines": p.get("patternLines", [])},
            "wall": {"grid": p.get("wall", [])},
            "floorLine": _tile_list(p.get("floorLine", [])),
            "hasFirstPlayerToken": False,
        }
    if seat_order:
        ordered = {n: players[n] for n in seat_order if n in players}
        for name, board in players.items():
            ordered.setdefault(name, board)
        players = ordered

    center_colors = snapshot.get("center") or []
    center: List[Any] = _tile_list(center_colors)
    if "firstPlayer" in center_colors:
        center.append("firstPlayer")

    return {
        "room": "",
        "round": round_number,
        "currentPlayer": seat_name if snapshot.get("myTurn") else "",
        "gameOver": False,
        "factories": [_tile_list(f) for f in snapshot.get("factories") or []],
        "center": center,
        "players": players,
        "source": "dom",
    }
