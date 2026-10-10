"""Rule extraction: retrieved rulebook text → structured RuleSpecs.

Second stage of the RAG-to-Logic pipeline. Two extraction paths:

* ``extract_rules_deterministic`` — retrieval + pattern parsing. Each
  known rule *topic* has a retrieval query and a parser that mines the
  retrieved chunk for parameters (penalty tables, bonus values, counts)
  or confirms the constraint's source sentence is present.
* ``extract_rules_llm`` — optional Claude-backed extraction producing
  the same RuleSpec JSON; falls back to the deterministic path on any
  failure so the pipeline never depends on network access.

Either way, the LLM is *out of the real-time move path*: extracted
specs are verified against the deterministic engine (``verify.py``)
before anything trusts them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .ingest import Chunk, RulebookIndex

KINDS = ("constraint", "scoring", "flow")

#: Engine predicate names a constraint RuleSpec may map onto
#: (see tiles.core.rules.check_action).
ENGINE_PREDICATES = (
    "phase_is_drafting",
    "color_exists",
    "source_exists",
    "source_has_color",
    "dest_exists",
    "wall_slot_open",
    "line_color_matches",
    "line_has_space",
)


@dataclass
class RuleSpec:
    """One structured, machine-readable rule mined from the rulebook."""

    id: str
    section: str
    text: str
    kind: str  # constraint | scoring | flow
    predicate: Optional[str] = None
    parameters: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "section": self.section,
            "text": self.text,
            "kind": self.kind,
            "predicate": self.predicate,
            "parameters": self.parameters,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RuleSpec":
        return cls(
            id=d["id"],
            section=d.get("section", ""),
            text=d.get("text", ""),
            kind=d.get("kind", "constraint"),
            predicate=d.get("predicate"),
            parameters=d.get("parameters", {}),
        )


# ---------------------------------------------------------------------------
# Deterministic extraction
# ---------------------------------------------------------------------------

Parser = Callable[[str], Optional[dict]]


def _parse_floor_penalties(text: str) -> Optional[dict]:
    negatives = [-int(m) for m in re.findall(r"-\s?(\d)", text)]
    if len(negatives) < 7:
        return None
    return {"penalties": negatives[:7]}


def _parse_bonuses(text: str) -> Optional[dict]:
    row = re.search(r"(\d+)\s+points?\s+for\s+each\s+complete\s+horizontal\s+row", text)
    col = re.search(r"(\d+)\s+points?\s+for\s+each\s+complete\s+vertical\s+column", text)
    color = re.search(r"(\d+)\s+points?\s+for\s+each\s+color", text)
    if not (row and col and color):
        return None
    return {
        "row": int(row.group(1)),
        "col": int(col.group(1)),
        "color": int(color.group(1)),
    }


def _parse_factory_counts(text: str) -> Optional[dict]:
    pairs = re.findall(r"(\d)\s+player\s+game:\s+(\d)\s+factory", text)
    counts = {int(players): int(factories) for players, factories in pairs}
    if set(counts) != {2, 3, 4}:
        return None
    return {"factories_by_players": counts}


def _parse_tile_supply(text: str) -> Optional[dict]:
    per_color = re.search(r"(\d+)\s+tiles\s+of\s+each\s+of\s+the\s+(\d)\s+colors", text)
    total = re.search(r"(\d+)\s+tiles:", text)
    if not (per_color and total):
        return None
    return {
        "tiles_per_color": int(per_color.group(1)),
        "colors": int(per_color.group(2)),
        "total": int(total.group(1)),
    }


def _parse_factory_fill(text: str) -> Optional[dict]:
    match = re.search(r"(\d)\s+tiles\s+drawn\s+from\s+the\s+bag", text)
    if not match:
        return None
    return {"tiles_per_factory": int(match.group(1))}


def _parse_isolated_score(text: str) -> Optional[dict]:
    match = re.search(r"scores\s+exactly\s+(\d)\s+point", text)
    if not match:
        return None
    return {"isolated": int(match.group(1))}


def _parse_min_score(text: str) -> Optional[dict]:
    match = re.search(r"never\s+drop\s+below\s+(\d)", text)
    if not match:
        return None
    return {"min_score": int(match.group(1))}


def _presence(*patterns: str) -> Parser:
    """Parser for constraint/flow rules with no numeric parameters: the
    chunk must contain every pattern (case-insensitive)."""

    def parse(text: str) -> Optional[dict]:
        if all(re.search(p, text, re.IGNORECASE) for p in patterns):
            return {}
        return None

    return parse


@dataclass(frozen=True)
class _Topic:
    id: str
    kind: str
    predicate: Optional[str]
    query: str
    parse: Parser


_TOPICS: List[_Topic] = [
    # Scoring rules with numeric parameters
    _Topic(
        "floor_penalties",
        "scoring",
        "floor_penalty",
        "floor line spaces penalty negative points left to right",
        _parse_floor_penalties,
    ),
    _Topic(
        "endgame_bonuses",
        "scoring",
        "end_game_bonuses",
        "final scoring bonus points complete horizontal row vertical column color",
        _parse_bonuses,
    ),
    _Topic(
        "placement_scoring",
        "scoring",
        "placement_score",
        "tile scored adjacency linked horizontal vertical chain points",
        _parse_isolated_score,
    ),
    _Topic(
        "score_floor_zero",
        "scoring",
        "min_score",
        "score never drop below zero marker",
        _parse_min_score,
    ),
    # Setup / flow rules with numeric parameters
    _Topic(
        "factory_counts",
        "flow",
        "factories_for_players",
        "number of factory displays player game",
        _parse_factory_counts,
    ),
    _Topic(
        "tile_supply",
        "flow",
        "tile_supply",
        "bag starts tiles of each colors",
        _parse_tile_supply,
    ),
    _Topic(
        "factory_fill",
        "flow",
        "deal_round",
        "fill each factory display tiles drawn from bag",
        _parse_factory_fill,
    ),
    # Drafting constraints (map onto engine predicates)
    _Topic(
        "draft_take_all",
        "constraint",
        "source_has_color",
        "take all tiles of that color factory display center",
        _presence(r"all tiles of that color", r"not actually present|actually holds"),
    ),
    _Topic(
        "wall_duplicate",
        "constraint",
        "wall_slot_open",
        "never place color wall row already holds",
        _presence(r"wall row already holds"),
    ),
    _Topic(
        "line_single_color",
        "constraint",
        "line_color_matches",
        "pattern line only one single color",
        _presence(r"one single color"),
    ),
    _Topic(
        "line_capacity",
        "constraint",
        "line_has_space",
        "pattern line already full may not add",
        _presence(r"already full"),
    ),
    _Topic(
        "game_over_no_moves",
        "constraint",
        "phase_is_drafting",
        "once game ended no further tiles drafted turns",
        _presence(r"no further tiles"),
    ),
    _Topic(
        "valid_color",
        "constraint",
        "color_exists",
        "exactly colors of tiles no other color",
        _presence(r"5 colors of tiles"),
    ),
    _Topic(
        "valid_source",
        "constraint",
        "source_exists",
        "only draft factory display in play player count",
        _presence(r"in play"),
    ),
    _Topic(
        "valid_destination",
        "constraint",
        "dest_exists",
        "board has pattern lines topmost bottom",
        _presence(r"5 pattern lines"),
    ),
    # Flow rules verified behaviorally
    _Topic(
        "first_player_token",
        "flow",
        "first_player_token",
        "first player token center floor line first turn next round",
        _presence(r"first player token", r"floor line", r"next round"),
    ),
    _Topic(
        "game_end_trigger",
        "flow",
        "game_end_trigger",
        "game ends completed full horizontal row wall",
        _presence(r"horizontal row"),
    ),
    _Topic(
        "bag_refill",
        "flow",
        "bag_refill",
        "bag empty refill tiles box lid",
        _presence(r"refill the bag"),
    ),
    _Topic(
        "tie_break",
        "flow",
        "tie_break",
        "tie most complete horizontal rows wins",
        _presence(r"most complete"),
    ),
]


def extract_rules_deterministic(index: RulebookIndex, k: int = 6) -> List[RuleSpec]:
    """Retrieval + pattern parsing over the indexed rulebook."""
    specs: List[RuleSpec] = []
    for topic in _TOPICS:
        for chunk in index.search(topic.query, k=k):
            parameters = topic.parse(chunk.text)
            if parameters is not None:
                specs.append(
                    RuleSpec(
                        id=topic.id,
                        section=chunk.section,
                        text=chunk.text,
                        kind=topic.kind,
                        predicate=topic.predicate,
                        parameters=parameters,
                    )
                )
                break
    return specs


# ---------------------------------------------------------------------------
# LLM-backed extraction (optional; falls back to deterministic)
# ---------------------------------------------------------------------------

_LLM_PROMPT = """You are the rule-extraction stage of a board-game AI \
pipeline. Below is the full Azul rulebook, split into [section] chunks. \
Extract the rules as a JSON array of objects with exactly these keys:
- "id": snake_case identifier, use these ids where applicable: {ids}
- "section": the [section] tag the rule came from
- "text": the source sentence(s), verbatim
- "kind": one of "constraint", "scoring", "flow"
- "predicate": for constraints, the matching engine predicate from \
{predicates}; for scoring/flow use the id-appropriate name or null
- "parameters": numeric parameters as an object, e.g. \
{{"penalties": [-1,-1,-2,-2,-2,-3,-3]}} for floor penalties, \
{{"row": 2, "col": 7, "color": 10}} for end-game bonuses, \
{{"factories_by_players": {{"2": 5, "3": 7, "4": 9}}}} for factory counts

Respond with ONLY the JSON array.

RULEBOOK:
{rulebook}
"""


def extract_rules_llm(
    index: RulebookIndex, model: str = "claude-opus-5"
) -> List[RuleSpec]:
    """Claude-backed extraction of the same RuleSpec structure.

    Requires the ``anthropic`` package and credentials (an
    ``ANTHROPIC_API_KEY`` or an ``ant auth login`` profile). Any failure
    — import, auth, network, malformed JSON — falls back to the
    deterministic extraction so callers always get specs.
    """
    try:
        import anthropic

        client = anthropic.Anthropic()
        prompt = _LLM_PROMPT.format(
            ids=", ".join(t.id for t in _TOPICS),
            predicates=", ".join(ENGINE_PREDICATES),
            rulebook=index.full_text(),
        )
        response = client.messages.create(
            model=model,
            max_tokens=16000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        match = re.search(r"\[.*\]", text, re.DOTALL)
        raw = json.loads(match.group(0) if match else text)
        specs = []
        for item in raw:
            spec = RuleSpec.from_dict(item)
            # Normalise JSON string keys back to ints where expected.
            if "factories_by_players" in spec.parameters:
                spec.parameters["factories_by_players"] = {
                    int(k): int(v)
                    for k, v in spec.parameters["factories_by_players"].items()
                }
            specs.append(spec)
        if not specs:
            raise ValueError("LLM returned no rules")
        return specs
    except Exception:
        return extract_rules_deterministic(index)
