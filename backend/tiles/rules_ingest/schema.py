"""Structured rules, the engine's ground truth, comparison and conversion to a RulesConfig."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Dict, List, Optional

from tiles.azul.config import DEFAULT_RULES, RulesConfig
from tiles.azul.rules import WALL_PATTERN


@dataclass
class RuleSet:
    colors: Optional[List[str]] = None
    tiles_per_color: Optional[int] = None
    tiles_per_factory: Optional[int] = None
    factories_by_players: Optional[Dict[int, int]] = None
    pattern_capacities: Optional[List[int]] = None
    floor_penalties: Optional[List[int]] = None
    row_bonus: Optional[int] = None
    column_bonus: Optional[int] = None
    color_bonus: Optional[int] = None
    wall_first_row: Optional[List[str]] = None
    wall_shift: Optional[int] = None            # +1 = each row shifted one place right
    game_end_trigger: Optional[str] = None      # "row" | "column" | "color"
    token_on_floor: Optional[bool] = None
    token_starts_next_round: Optional[bool] = None
    isolated_tile_score: Optional[int] = None
    scores_both_directions: Optional[bool] = None

    def to_dict(self) -> dict:
        return asdict(self)


FIELDS = [f.name for f in fields(RuleSet)]


def ground_truth() -> RuleSet:
    """The values the engine implements (rules.py / config.py)."""
    d = DEFAULT_RULES
    return RuleSet(
        colors=[c.value for c in WALL_PATTERN[0]],
        tiles_per_color=d.tiles_per_color,
        tiles_per_factory=d.tiles_per_factory,
        factories_by_players=dict(d.factories_by_players),
        pattern_capacities=[1, 2, 3, 4, 5],
        floor_penalties=list(d.floor_penalties),
        row_bonus=d.row_bonus,
        column_bonus=d.column_bonus,
        color_bonus=d.color_bonus,
        wall_first_row=[c.value for c in WALL_PATTERN[0]],
        wall_shift=1,
        game_end_trigger="row",
        token_on_floor=True,
        token_starts_next_round=True,
        isolated_tile_score=1,
        scores_both_directions=True,
    )


def compare(extracted: RuleSet, truth: Optional[RuleSet] = None) -> Dict[str, bool]:
    """Field-by-field exact match (missing counts as wrong)."""
    truth = truth or ground_truth()
    out = {}
    for name in FIELDS:
        a, b = getattr(extracted, name), getattr(truth, name)
        out[name] = a is not None and a == b
    return out


def wall_matches_standard(rs: RuleSet) -> bool:
    """Does the extracted wall description rebuild the standard layout? (Verified, not applied.)"""
    if not rs.wall_first_row or rs.wall_shift is None or len(rs.wall_first_row) != 5:
        return False
    row = rs.wall_first_row
    built = [[row[(c - r * rs.wall_shift) % 5] for c in range(5)] for r in range(5)]
    return built == [[c.value for c in r] for r in WALL_PATTERN]


def to_config(rs: RuleSet, strict: bool = True) -> RulesConfig:
    """Build a RulesConfig from extracted rules.

    strict: raise if any parameter the engine needs is missing. Otherwise fall back to the
    standard value for what is missing (use only for exploration).
    """
    needed = ["tiles_per_color", "tiles_per_factory", "factories_by_players", "floor_penalties",
              "row_bonus", "column_bonus", "color_bonus"]
    missing = [n for n in needed if getattr(rs, n) is None]
    if strict and missing:
        raise ValueError(f"rulebook did not yield: {', '.join(missing)}")
    d = DEFAULT_RULES
    return RulesConfig(
        floor_penalties=tuple(rs.floor_penalties) if rs.floor_penalties else d.floor_penalties,
        row_bonus=rs.row_bonus if rs.row_bonus is not None else d.row_bonus,
        column_bonus=rs.column_bonus if rs.column_bonus is not None else d.column_bonus,
        color_bonus=rs.color_bonus if rs.color_bonus is not None else d.color_bonus,
        tiles_per_color=rs.tiles_per_color if rs.tiles_per_color is not None else d.tiles_per_color,
        tiles_per_factory=rs.tiles_per_factory if rs.tiles_per_factory is not None else d.tiles_per_factory,
        factories_by_players=dict(rs.factories_by_players) if rs.factories_by_players else dict(d.factories_by_players),
    )
