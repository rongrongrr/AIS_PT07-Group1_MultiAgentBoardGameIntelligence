"""Azul game state.

Design notes
------------
The state is the single source of truth consumed by every agent in the
Decision Stack. It is optimised for two competing consumers:

* the Validator / MCTS engine, which needs *fast cloning and mutation*
  (walls are 25-bit integers, tile pools are 5-int count vectors), and
* the Explainer / frontend / ledger, which need a *semantic JSON view*
  (``to_dict`` / ``from_dict``).

Colors are small ints everywhere inside the engine; names only appear at
serialization boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, List, Optional

# ---------------------------------------------------------------------------
# Colors
# ---------------------------------------------------------------------------

BLUE, YELLOW, RED, BLACK, WHITE = range(5)
NUM_COLORS = 5
COLOR_NAMES = ["blue", "yellow", "red", "black", "white"]
FIRST_PLAYER = 5  # sentinel used only in floor lines
TILES_PER_COLOR = 20

FLOOR_PENALTIES = (-1, -1, -2, -2, -2, -3, -3)
FLOOR_CAPACITY = len(FLOOR_PENALTIES)

# The standard Azul wall: color at (row, col) is (col - row) mod 5.
# Row 0: blue yellow red black white; each row shifts right by one.


def wall_color_at(row: int, col: int) -> int:
    return (col - row) % NUM_COLORS


def wall_col_for(row: int, color: int) -> int:
    return (color + row) % NUM_COLORS


def wall_bit(row: int, col: int) -> int:
    return 1 << (row * 5 + col)


def color_name(color: int) -> str:
    return "firstPlayer" if color == FIRST_PLAYER else COLOR_NAMES[color]


def color_from_name(name: str) -> int:
    if name == "firstPlayer":
        return FIRST_PLAYER
    return COLOR_NAMES.index(name)


def factories_for_players(num_players: int) -> int:
    return {2: 5, 3: 7, 4: 9}[num_players]


# ---------------------------------------------------------------------------
# Player board
# ---------------------------------------------------------------------------


@dataclass
class PlayerBoard:
    """One player's personal board.

    ``wall`` is a 25-bit int (bit r*5+c set = tile placed).
    ``pattern_colors[r]`` is the color occupying pattern line ``r`` or -1.
    ``pattern_counts[r]`` is how many tiles sit on that line (0..r+1).
    ``floor`` lists tile colors on the floor line, possibly including
    the FIRST_PLAYER sentinel; it may exceed FLOOR_CAPACITY (extra tiles
    still go to the lid but score nothing beyond the 7 penalty slots).
    """

    name: str = "player"
    wall: int = 0
    pattern_colors: List[int] = field(default_factory=lambda: [-1] * 5)
    pattern_counts: List[int] = field(default_factory=lambda: [0] * 5)
    floor: List[int] = field(default_factory=list)
    score: int = 0

    # -- queries ------------------------------------------------------------

    def wall_has(self, row: int, col: int) -> bool:
        return bool(self.wall & wall_bit(row, col))

    def wall_has_color(self, row: int, color: int) -> bool:
        return self.wall_has(row, wall_col_for(row, color))

    def pattern_space(self, row: int) -> int:
        return (row + 1) - self.pattern_counts[row]

    def can_place(self, row: int, color: int) -> bool:
        """Can tiles of ``color`` legally go on pattern line ``row``?"""
        if self.wall_has_color(row, color):
            return False
        line_color = self.pattern_colors[row]
        if line_color != -1 and line_color != color:
            return False
        return self.pattern_counts[row] < row + 1

    def completed_rows(self) -> int:
        return sum(
            1 for r in range(5) if all(self.wall_has(r, c) for c in range(5))
        )

    def has_first_player_token(self) -> bool:
        return FIRST_PLAYER in self.floor

    def floor_penalty(self) -> int:
        return sum(FLOOR_PENALTIES[: min(len(self.floor), FLOOR_CAPACITY)])

    # -- serialization -------------------------------------------------------

    def wall_grid(self) -> List[List[bool]]:
        return [[self.wall_has(r, c) for c in range(5)] for r in range(5)]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "score": self.score,
            "wall": self.wall_grid(),
            "pattern_lines": [
                [color_name(self.pattern_colors[r])] * self.pattern_counts[r]
                for r in range(5)
            ],
            "floor_line": [color_name(t) for t in self.floor],
            "has_first_player_token": self.has_first_player_token(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> PlayerBoard:
        board = cls(name=d.get("name", "player"), score=d.get("score", 0))
        for r, row in enumerate(d.get("wall", [])):
            for c, filled in enumerate(row):
                if filled:
                    board.wall |= wall_bit(r, c)
        for r, line in enumerate(d.get("pattern_lines", [[]] * 5)):
            tiles = [t for t in line if t]
            if tiles:
                board.pattern_colors[r] = color_from_name(tiles[0])
                board.pattern_counts[r] = len(tiles)
        board.floor = [color_from_name(t) for t in d.get("floor_line", [])]
        return board

    def clone(self) -> PlayerBoard:
        return PlayerBoard(
            name=self.name,
            wall=self.wall,
            pattern_colors=self.pattern_colors[:],
            pattern_counts=self.pattern_counts[:],
            floor=self.floor[:],
            score=self.score,
        )


# ---------------------------------------------------------------------------
# Game state
# ---------------------------------------------------------------------------

PHASE_DRAFTING = "drafting"
PHASE_GAME_OVER = "game_over"


@dataclass
class GameState:
    """Full Azul game state.

    ``factories[i]`` and ``center``/``bag``/``lid`` are 5-int count
    vectors indexed by color. ``center_has_fpt`` tracks the first-player
    token separately.
    """

    num_players: int = 2
    factories: List[List[int]] = field(default_factory=list)
    center: List[int] = field(default_factory=lambda: [0] * NUM_COLORS)
    center_has_fpt: bool = True
    bag: List[int] = field(
        default_factory=lambda: [TILES_PER_COLOR] * NUM_COLORS
    )
    lid: List[int] = field(default_factory=lambda: [0] * NUM_COLORS)
    players: List[PlayerBoard] = field(default_factory=list)
    current_player: int = 0
    round_number: int = 1
    phase: str = PHASE_DRAFTING
    # Player who takes the first turn next round (took FPT this round).
    next_first_player: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.players:
            self.players = [
                PlayerBoard(name=f"player_{i}") for i in range(self.num_players)
            ]
        if not self.factories:
            self.factories = [
                [0] * NUM_COLORS
                for _ in range(factories_for_players(self.num_players))
            ]

    # -- queries ------------------------------------------------------------

    @property
    def is_game_over(self) -> bool:
        return self.phase == PHASE_GAME_OVER

    def drafting_exhausted(self) -> bool:
        """True when no tiles remain to draft (round ends)."""
        if any(any(f) for f in self.factories):
            return False
        return not any(self.center)

    def current_board(self) -> PlayerBoard:
        return self.players[self.current_player]

    def scores(self) -> List[int]:
        return [p.score for p in self.players]

    def winner(self) -> Optional[int]:
        """Winning player index (ties broken by completed rows), or None."""
        if not self.is_game_over:
            return None
        best = max(
            range(self.num_players),
            key=lambda i: (
                self.players[i].score,
                self.players[i].completed_rows(),
            ),
        )
        return best

    def iter_players(self) -> Iterator[PlayerBoard]:
        return iter(self.players)

    # -- serialization -------------------------------------------------------

    def to_dict(self) -> dict:
        def expand(counts: List[int]) -> List[str]:
            out: List[str] = []
            for color, n in enumerate(counts):
                out.extend([COLOR_NAMES[color]] * n)
            return out

        center = expand(self.center)
        if self.center_has_fpt:
            center.append("firstPlayer")
        return {
            "num_players": self.num_players,
            "round": self.round_number,
            "phase": self.phase,
            "current_player": self.current_player,
            "factories": [expand(f) for f in self.factories],
            "center_pool": center,
            "bag": list(self.bag),
            "lid": list(self.lid),
            "players": [p.to_dict() for p in self.players],
        }

    @classmethod
    def from_dict(cls, d: dict) -> GameState:
        def collapse(tiles: List[str]) -> List[int]:
            counts = [0] * NUM_COLORS
            for t in tiles:
                if t != "firstPlayer":
                    counts[color_from_name(t)] += 1
            return counts

        players = [PlayerBoard.from_dict(p) for p in d["players"]]
        state = cls(
            num_players=d.get("num_players", len(players)),
            factories=[collapse(f) for f in d["factories"]],
            center=collapse(d.get("center_pool", [])),
            center_has_fpt="firstPlayer" in d.get("center_pool", []),
            bag=list(d.get("bag", [0] * NUM_COLORS)),
            lid=list(d.get("lid", [0] * NUM_COLORS)),
            players=players,
            current_player=d.get("current_player", 0),
            round_number=d.get("round", 1),
            phase=d.get("phase", PHASE_DRAFTING),
        )
        return state

    def clone(self) -> GameState:
        return GameState(
            num_players=self.num_players,
            factories=[f[:] for f in self.factories],
            center=self.center[:],
            center_has_fpt=self.center_has_fpt,
            bag=self.bag[:],
            lid=self.lid[:],
            players=[p.clone() for p in self.players],
            current_player=self.current_player,
            round_number=self.round_number,
            phase=self.phase,
            next_first_player=self.next_first_player,
        )
