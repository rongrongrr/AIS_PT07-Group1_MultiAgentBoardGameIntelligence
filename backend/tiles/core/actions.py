"""Azul actions.

An action is: take *all* tiles of one color from one source (a factory
or the center pool) and place them on one pattern line (overflow to the
floor) or entirely on the floor.

Every action also has a stable integer id so that RL-style consumers
(action masks, policy heads) can address the full 300-slot action space:

    action_id = source_slot * 30 + color * 6 + dest_slot

where ``source_slot`` is the factory index (0..8) or 9 for the center,
and ``dest_slot`` is the pattern row (0..4) or 5 for the floor.
"""

from __future__ import annotations

from dataclasses import dataclass

from .state import COLOR_NAMES, color_from_name

CENTER = -1  # source_index value meaning "the center pool"
FLOOR = -1  # dest_row value meaning "the floor line"

MAX_SOURCES = 10  # 9 factories + center
MAX_ACTIONS = MAX_SOURCES * 5 * 6  # 300


@dataclass(frozen=True)
class Action:
    source_index: int  # 0..8 factory, CENTER (-1) for center pool
    color: int  # 0..4
    dest_row: int  # 0..4 pattern line, FLOOR (-1) for floor

    @property
    def from_center(self) -> bool:
        return self.source_index == CENTER

    @property
    def to_floor(self) -> bool:
        return self.dest_row == FLOOR

    @property
    def action_id(self) -> int:
        source_slot = 9 if self.from_center else self.source_index
        dest_slot = 5 if self.to_floor else self.dest_row
        return source_slot * 30 + self.color * 6 + dest_slot

    @classmethod
    def from_action_id(cls, action_id: int) -> Action:
        source_slot, rest = divmod(action_id, 30)
        color, dest_slot = divmod(rest, 6)
        return cls(
            source_index=CENTER if source_slot == 9 else source_slot,
            color=color,
            dest_row=FLOOR if dest_slot == 5 else dest_slot,
        )

    def to_dict(self) -> dict:
        return {
            "source_type": "center" if self.from_center else "factory",
            "source_index": None if self.from_center else self.source_index,
            "color": COLOR_NAMES[self.color],
            "destination": "floor" if self.to_floor else "pattern_line",
            "destination_row": None if self.to_floor else self.dest_row,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Action:
        return cls(
            source_index=(
                CENTER
                if d.get("source_type") == "center"
                else int(d["source_index"])
            ),
            color=color_from_name(d["color"]),
            dest_row=(
                FLOOR
                if d.get("destination") == "floor"
                else int(d["destination_row"])
            ),
        )

    def describe(self) -> str:
        source = "the center" if self.from_center else f"factory {self.source_index + 1}"
        dest = "the floor" if self.to_floor else f"pattern line {self.dest_row + 1}"
        return f"take {COLOR_NAMES[self.color]} from {source} to {dest}"

    def __str__(self) -> str:  # compact, for logs
        src = "C" if self.from_center else f"F{self.source_index}"
        dst = "floor" if self.to_floor else f"row{self.dest_row}"
        return f"{src}:{COLOR_NAMES[self.color]}->{dst}"
