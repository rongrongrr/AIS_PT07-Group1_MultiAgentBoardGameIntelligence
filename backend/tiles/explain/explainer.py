"""Explainer: turns a decision into a natural-language rationale built from checkable facts.

Every sentence is generated from a structured fact computed from the rules engine (what the move
completes, what it costs on the floor, whom it denies, how it compares with the alternatives), so a
rationale can never claim something the position does not support. ``facts`` is returned with the
text so the claims can be verified independently (see tests/test_explainer.py, which re-derives them
by simulating the move). An optional ``LLMExplainer`` rewrites the text from the facts only.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

from tiles.azul.rules import (
    calculate_floor_penalty,
    get_pattern_line_color,
    pattern_line_space,
    score_tile_placement,
    wall_column_for_color,
)
from tiles.models.schemas import DestinationType, GameAction, GameStateData, SourceType


def _value(x) -> str:
    return getattr(x, "value", str(x))


def _count_picked(state: GameStateData, action: GameAction) -> int:
    if action.source_type == SourceType.FACTORY and action.source_index is not None:
        return sum(1 for t in state.factories[action.source_index] if _value(t) == action.color.value)
    return sum(1 for t in state.center_pool if t == action.color.value)


def move_facts(state: GameStateData, player_index: int, action: GameAction) -> Dict:
    """Structured, engine-derived facts about a move (no judgement, just consequences)."""
    me = state.players[player_index]
    picked = _count_picked(state, action)
    facts: Dict = {
        "player": me.name,
        "color": action.color.value,
        "picked": picked,
        "source": "center" if action.source_type == SourceType.CENTER else f"factory {action.source_index + 1}",
        "destination": "floor" if action.destination == DestinationType.FLOOR else f"row {action.destination_row + 1}",
        "leaves_in_center": 0,
        "takes_token": False,
        "overflow": 0,
        "completes_line": False,
        "line_points": 0,
        "line_fill": None,
        "floor_penalty": 0,
        "denies": [],
    }
    if action.source_type == SourceType.FACTORY:
        facts["leaves_in_center"] = sum(
            1 for t in state.factories[action.source_index] if _value(t) != action.color.value)
    else:
        facts["takes_token"] = "firstPlayer" in state.center_pool and not me.has_first_player_token

    floor_now = len(me.floor_line) + (1 if me.has_first_player_token else 0)
    spill = picked
    if action.destination == DestinationType.PATTERN_LINE:
        row = action.destination_row
        space = pattern_line_space(me, row)
        placed = min(picked, space)
        spill = picked - placed
        filled_after = (row + 1) - space + placed
        facts["line_fill"] = f"{filled_after}/{row + 1}"
        if placed >= space:
            facts["completes_line"] = True
            col = wall_column_for_color(row, action.color)
            wall = [r[:] for r in me.wall]
            wall[row][col] = True
            facts["line_points"] = score_tile_placement(wall, row, col)
    facts["overflow"] = spill
    extra = spill + (1 if facts["takes_token"] else 0)
    facts["floor_penalty"] = calculate_floor_penalty(floor_now + extra) - calculate_floor_penalty(floor_now)

    for i, opp in enumerate(state.players):
        if i == player_index:
            continue
        for row in range(5):
            if get_pattern_line_color(opp, row) == action.color and pattern_line_space(opp, row) > 0:
                facts["denies"].append(opp.name)
                break
    return facts


def _describe(a: Dict) -> str:
    where = "the center" if a["source"] == "center" else a["source"].capitalize()
    dest = "the floor" if a["destination"] == "floor" else a["destination"]
    return f"{a['color']} from {where} to {dest}"


class Explainer:
    """Deterministic template-based explainer."""

    def explain(self, state: GameStateData, player_index: int, action: GameAction,
                explanation: Optional[dict] = None) -> Dict:
        f = move_facts(state, player_index, action)
        name = f["player"]
        where = "the center" if f["source"] == "center" else f["source"].capitalize()
        parts: List[str] = []

        if f["destination"] == "floor":
            parts.append(f"{name} takes {f['picked']} {f['color']} from {where} and puts them straight on the floor, "
                         f"costing {abs(f['floor_penalty'])} point{'s' if abs(f['floor_penalty']) != 1 else ''}.")
        else:
            parts.append(f"{name} takes {f['picked']} {f['color']} from {where} and places them on {f['destination']} "
                         f"({f['line_fill']} filled).")
            if f["completes_line"]:
                parts.append(f"That completes the line, worth {f['line_points']} point{'s' if f['line_points'] != 1 else ''} "
                             f"when it is moved onto the wall.")
            if f["overflow"]:
                parts.append(f"{f['overflow']} tile{'s' if f['overflow'] != 1 else ''} overflow onto the floor "
                             f"({f['floor_penalty']} points).")
        if f["takes_token"]:
            parts.append("It also takes the first-player token, which counts as a floor tile but means going first next round.")
        if f["leaves_in_center"]:
            parts.append(f"The other {f['leaves_in_center']} tile{'s' if f['leaves_in_center'] != 1 else ''} "
                         f"move to the center for the opponent{'s' if len(state.players) > 2 else ''}.")
        if f["denies"]:
            parts.append(f"Taking {f['color']} also denies {', '.join(f['denies'])} a colour they are building.")

        if explanation and explanation.get("top_alternatives") and len(explanation["top_alternatives"]) > 1:
            alts = explanation["top_alternatives"]
            first, second = alts[0], alts[1]
            gap = first["score"] - second["score"]
            alt = GameAction(**{k: (_enum_or_raw(v)) for k, v in second["action"].items()})
            af = move_facts(state, player_index, alt)
            parts.append(f"The {explanation.get('model', 'model')} rated it {first['score']:.1f}, "
                         f"{gap:.1f} ahead of the next option ({_describe(af)}, {second['score']:.1f}).")
        adapt = (explanation or {}).get("adaptation")
        if adapt and adapt.get("opponents"):
            bits = [f"{n} looks like {e.get('style') or e.get('archetype')} ({int(e['confidence'] * 100)}% sure)"
                    for n, e in adapt["opponents"].items()]
            parts.append("Opponent read: " + "; ".join(bits) + ".")

        return {"rationale": " ".join(parts), "facts": f}

    def commentary(self, state: GameStateData, player_index: int, action: GameAction) -> str:
        """One short spectator-style line."""
        f = move_facts(state, player_index, action)
        where = "the center" if f["source"] == "center" else f["source"]
        bits = [f"{f['player']} takes {f['picked']} {f['color']} from {where}"]
        bits.append("onto the floor" if f["destination"] == "floor" else f"onto {f['destination']}")
        if f["completes_line"]:
            bits.append(f"completing the line for {f['line_points']}")
        if f["overflow"]:
            bits.append(f"spilling {f['overflow']} to the floor")
        if f["denies"]:
            bits.append(f"and denying {', '.join(f['denies'])}")
        return ", ".join(bits) + "."


def _enum_or_raw(v):
    return v


class LLMExplainer(Explainer):
    """Rewrites the template rationale in a friendlier voice using a language model.

    ``complete`` is ``(system, user) -> str``. The model only sees the structured facts and the
    template text and is told not to add claims. Not benchmarked live (no API key here); on any
    failure the template rationale is returned.
    """

    SYSTEM = ("You rewrite board-game move explanations. Use ONLY the facts provided; do not add, remove "
              "or change any number, colour, row or player. Keep it to three sentences or fewer.")

    def __init__(self, complete: Callable[[str, str], str]):
        self.complete = complete

    def explain(self, state, player_index, action, explanation=None) -> Dict:
        base = super().explain(state, player_index, action, explanation)
        try:
            text = self.complete(self.SYSTEM, f"Facts: {base['facts']}\nDraft: {base['rationale']}").strip()
            if text:
                base["rationale_template"] = base["rationale"]
                base["rationale"] = text
        except Exception:
            pass
        return base
