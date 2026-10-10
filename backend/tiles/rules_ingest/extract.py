"""Rule extraction: retrieve the relevant passages for each rule, then parse them.

``PatternExtractor`` is deterministic (no model, no network). ``LLMExtractor`` asks a language
model to read the same retrieved passages and return JSON; it is wired and unit-tested with a
stub client but has not been benchmarked live (no API key was available).
"""

from __future__ import annotations

import json
import re
from typing import Callable, Dict, List, Optional, Tuple

from tiles.rules_ingest.retriever import Retriever, chunk, split_sentences
from tiles.rules_ingest.schema import FIELDS, RuleSet

NUMBER_WORDS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen twenty".split())}
NUMBER_WORDS["thirty"] = 30
_NUM = r"(?:\d+|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")"
_SIGN = r"(?:minus|negative|[-−–—])\s?"
_SIGNED = rf"(?:{_SIGN})?{_NUM}"
COLOR_WORDS = ["blue", "yellow", "red", "black", "white"]


def to_int(tok: str) -> Optional[int]:
    tok = tok.strip().lower()
    if tok.isdigit():
        return int(tok)
    return NUMBER_WORDS.get(tok)


def _clauses(text: str) -> List[str]:
    return [c.strip() for c in re.split(r"[.;]| - |\n", text) if c.strip()]


# --------------------------------------------------------------------------- parsers
# Each takes a passage and returns a value or None.

def parse_floor_penalties(text: str) -> Optional[List[int]]:
    # "minus one for the first, minus one for the second, ..."  (one value per ordinal slot)
    per_slot = re.findall(rf"({_SIGNED})\s+for\s+the\s+(?:first|second|third|fourth|fifth|sixth|seventh|eighth)", text, re.I)
    if len(per_slot) >= 4:
        vals = [to_int(re.sub(_SIGN, "", v, flags=re.I)) for v in per_slot]
        if None not in vals:
            return [-abs(v) for v in vals]
    # "the first two spaces cost 1 point, the next three 2 points, the last two 3 points"
    runs = re.findall(
        rf"(?:the\s+)?(?:first|next|following|last|final|remaining)\s+({_NUM})(?:\s+(?:spaces?|slots?|squares?))?"
        rf"[^.;,]{{0,40}}?({_NUM})\s+points?", text, re.I)
    if len(runs) >= 2:
        out: List[int] = []
        for count, val in runs:
            c, v = to_int(count), to_int(val)
            if c is None or v is None:
                return None
            out += [-v] * c
        return out
    # "slot 1 = -1, slot 2 = -1, ..." / "slot one costs one, slot two costs one, ..."
    slots = re.findall(rf"(?:slot|space|square|position)\s+({_NUM})\s*(?:=|:|costs?|is|-)?\s*({_SIGNED})", text, re.I)
    if len(slots) >= 4:
        pairs = [(to_int(a), to_int(re.sub(_SIGN, "", b, flags=re.I))) for a, b in slots]
        if all(x is not None and y is not None for x, y in pairs):
            return [-abs(v) for _, v in sorted(pairs)]
    # signed numbers separated only by spaces: "-1 -1 -2 -2 -2 -3 -3"
    spaced = re.search(rf"((?:{_SIGN}{_NUM})(?:\s+(?:{_SIGN}{_NUM})){{3,}})", text, re.I)
    if spaced:
        vals = [to_int(m) for m in re.findall(_NUM, spaced.group(1), re.I)]
        if None not in vals and len(vals) >= 4:
            return [-abs(v) for v in vals]
    seq = re.search(rf"({_SIGNED}(?:\s*(?:,|/|\||;|and|then|,\s*and)\s*{_SIGNED}){{3,}})", text, re.I)
    if seq:
        vals = [to_int(m) for m in re.findall(_NUM, seq.group(1), re.I)]
        if vals and None not in vals and len(vals) >= 4:
            return [-abs(v) for v in vals]
    groups = re.findall(
        rf"({_NUM})\s+(?:spaces?|squares?|slots?|positions?|tiles?)[^.;]{{0,60}}?"
        rf"(?:cost|costs|lose|loses|penalt\w+|worth|subtract\w*)[^.;]{{0,30}}?({_NUM})\s+points?\s+each", text, re.I)
    if groups:
        out = []
        for count, pts in groups:
            c, p = to_int(count), to_int(pts)
            if c is None or p is None:
                return None
            out += [-p] * c
        return out
    return None


def _points_in(text: str) -> Optional[int]:
    for pat in (rf"({_NUM})\s+(?:extra\s+|bonus\s+|additional\s+)?points?",
                rf"(?:worth|scores?|gives?|earns?|awards?|grants?|adds?|gain|reward\w*\s+with)\s+(?:you\s+)?(?:just\s+)?({_NUM})",
                rf"\+\s*({_NUM})"):
        m = re.search(pat, text, re.I)
        if m:
            return to_int(m.group(1))
    return None


def parse_bonus(text: str, kind: str) -> Optional[int]:
    key = {"row": r"horizontal|\brows?\b|across", "column": r"vertical|column|\bdown\b|\blines?\b", "color": r"colou?r|\bhues?\b|\bsets?\b"}[kind]
    other = {"row": r"vertical|column|\bdown\b", "column": r"horizontal|across|\brows?\b", "color": r"horizontal|vertical|across|\bdown\b"}[kind]
    # clause level first (lists like "2 points for rows, 7 for columns"), then whole sentence
    for clause in re.split(r"[;,]|\band\b(?=\s+(?:\d|ten|seven|two|five))", text):
        if re.search(key, clause, re.I) and not re.search(other, clause, re.I):
            pts = _points_in(clause)
            if pts is not None:
                return pts
    for sent in split_sentences(text):
        if re.search(key, sent, re.I) and not re.search(other, sent, re.I):
            pts = _points_in(sent)
            if pts is not None:
                return pts
    return None


def parse_factories(text: str) -> Optional[Dict[int, int]]:
    out: Dict[int, int] = {}
    play = r"(?:players?|play|take\s+part|participate|are\s+playing)"
    fac = r"(?:factory|factories|(?:factory\s+)?displays?)"
    for clause in _clauses(text):
        for m in re.finditer(rf"({_NUM})[- ]?{play}\b[^.;]*?({_NUM})\s+{fac}", clause, re.I):
            p, f = to_int(m.group(1)), to_int(m.group(2))
            if p and f:
                out.setdefault(p, f)
        for m in re.finditer(rf"({_NUM})\s+(?:participants?|people|persons?|gamers?)[^.;]*?({_NUM})\s+{fac}", clause, re.I):
            p, f = to_int(m.group(1)), to_int(m.group(2))
            if p and f:
                out.setdefault(p, f)
        for m in re.finditer(rf"({_NUM})\s*\(\s*for\s+({_NUM})\s+players?\s*\)", clause, re.I):
            f, p = to_int(m.group(1)), to_int(m.group(2))
            if p and f:
                out.setdefault(p, f)
        for m in re.finditer(rf"({_NUM})[- ]player\s+\w+[^.;]*?({_NUM})\s+{fac}", clause, re.I):
            p, f = to_int(m.group(1)), to_int(m.group(2))
            if p and f:
                out.setdefault(p, f)
        for m in re.finditer(rf"({_NUM})\s+{fac}[^.;]*?(?:for|with|when|if)\s+({_NUM})\s+{play}", clause, re.I):
            f, p = to_int(m.group(1)), to_int(m.group(2))
            if p and f:
                out.setdefault(p, f)
        for m in re.finditer(rf"({_NUM})\s+{fac}\s+when\s+({_NUM})\s+{play}", clause, re.I):
            f, p = to_int(m.group(1)), to_int(m.group(2))
            if p and f:
                out.setdefault(p, f)
        # comma-separated list: "N when P play, M when Q play"
        for m in re.finditer(rf"({_NUM})\s+when\s+({_NUM})\s+{play}", text, re.I):
            f, p = to_int(m.group(1)), to_int(m.group(2))
            if p and f:
                out.setdefault(p, f)
    return out or None


def parse_tiles_per_factory(text: str) -> Optional[int]:
    for sent in split_sentences(text):
        if re.search(r"(each|every|per|on)\s+(?:single\s+)?(?:factory|display)|(?:factory|displays?)\s+(?:\w+\s+)?(?:gets|receives|holds?|starts?)", sent, re.I):
            sans = re.sub(rf"{_NUM}[- ]?players?", "", sent, flags=re.I)
            m = re.search(rf"({_NUM})\s+(?:random\s+)?tiles?", sans, re.I) or re.search(
                rf"({_NUM})\s+(?:to|on|onto|for)\s+(?:each|every)", sans, re.I) or re.search(
                rf"(?:gets|receives|holds|with)\s+({_NUM})\b", sans, re.I)
            if m:
                return to_int(m.group(1))
    return None


def parse_tiles_per_color(text: str) -> Optional[int]:
    for sent in split_sentences(text):
        if not re.search(r"(?:each|every|per)\s+colou?r|colou?r\s+by\s+colou?r", sent, re.I):
            continue
        for pat in (rf"({_NUM})\s+(?:tiles?\s+)?(?:of\s+(?:each|every)|per|in\s+(?:each|every))\s+colou?r",
                    rf"(?:each|every)\s+colou?r\s+(?:has|comes|includes|contains|appears|is\s+represented)[^.;]*?({_NUM})\s+tiles?",
                    rf"(?:supply|bag)\s+contains\s+({_NUM})\s+tiles?",
                    rf"there\s+are\s+({_NUM})\s+in\s+(?:every|each)\s+colou?r",
                    rf"^({_NUM})\s+tiles?\s+of\s+(?:every|each)\s+colou?r",
                    rf"({_NUM})\s+tiles?\b"):
            m = re.search(pat, sent, re.I)
            if m:
                return to_int(m.group(1))
    return None


def parse_colors(text: str) -> Optional[List[str]]:
    """Tile colours: the distinct colour words, in order, of a sentence that is about colours/tiles."""
    for sent in split_sentences(text):
        if not re.search(r"colou?rs?|hues?|tiles?", sent, re.I):
            continue
        if re.search(r"first\s+row|top\s+row|row\s+(?:one|1)\b|row\s+1\b", sent, re.I):
            continue                                   # that is the wall layout, not the tile set
        found: List[str] = []
        for w in re.findall(r"\b(" + "|".join(COLOR_WORDS) + r")\b", sent, re.I):
            if w.lower() not in found:
                found.append(w.lower())
        if len(found) >= 5:
            return found
    return None


def parse_pattern_capacities(text: str) -> Optional[List[int]]:
    nums = [to_int(x) for x in re.findall(rf"{_NUM}", text, re.I)]
    nums = [x for x in nums if x is not None]
    best: List[int] = []
    for i in range(len(nums)):
        run = [nums[i]]
        for x in nums[i + 1:]:
            if x == run[-1] + 1:
                run.append(x)
            elif x != run[-1]:
                break
        if len(run) > len(best):
            best = run
    if len(best) >= 3:
        return best
    single = re.search(rf"(?:single|one)\s+tile[^.]*?({_NUM})\b(?!\s*tiles?\s+longer)", text, re.I)
    if single and (to_int(single.group(1)) or 0) >= 3:
        return list(range(1, to_int(single.group(1)) + 1))
    rng = re.search(rf"({_NUM})\s*(?:to|through|-|\u2013|up to)\s*({_NUM})", text, re.I)
    if rng:
        a, b = to_int(rng.group(1)), to_int(rng.group(2))
        if a is not None and b is not None and b > a:
            return list(range(a, b + 1))
    return None


def parse_wall_first_row(text: str) -> Optional[List[str]]:
    for sent in split_sentences(text):
        if re.search(r"first\s+row|top\s+row|upper\s+row|uppermost|row\s+(?:one|1)\b|1st\s+row", sent, re.I):
            found = re.findall(r"\b(" + "|".join(COLOR_WORDS) + r")\b", sent, re.I)
            if len(found) >= 4:
                return [f.lower() for f in found]
    return None


def parse_wall_shift(text: str) -> Optional[int]:
    verbs = r"shift\w*|offset|moved?\b|slid\w*|rotat\w+|displac\w+|slips?|steps?|starts?\s+\w+\s+further|further"
    for sent in split_sentences(text):
        if not re.search(r"\brows?\b", sent, re.I) or not re.search(verbs, sent, re.I):
            continue
        direction = None
        if re.search(r"\bleft(?:wards?)?\b", sent, re.I):
            direction = -1
        elif re.search(r"\bright(?:wards?)?\b", sent, re.I):
            direction = 1
        if direction is None:
            continue
        amount = None
        for pat in (rf"(?:by|steps?|moved?|shifted?|slid\w*|slips?|displaced|rotated?|offset)\s+(?:by\s+)?({_NUM}|a\s+single)\b",
                    rf"({_NUM}|a\s+single)\s+(?:place|space|square|column|position|step)s?",
                    rf"({_NUM})\s+(?:to\s+the\s+)?(?:left|right)",
                    rf"starts?\s+({_NUM})\s"):
            m = re.search(pat, sent, re.I)
            if m:
                tok = m.group(1).lower()
                amount = 1 if tok == "a single" else to_int(tok)
                break
        return direction * (amount or 1)
    return None


def parse_end_trigger(text: str) -> Optional[str]:
    cue = (r"last\s+round|final\s+round|game\s+(?:is\s+)?(?:ends?|over|finish\w*)|"
           r"(?:ends?|finish\w*|over|triggered?)\b[^.]*\b(?:game|round)|(?:game|round|play)\b[^.]*\b(?:ends?|finish\w*|over|triggered?)|"
           r"end\s+of\s+the\s+game")
    for sent in split_sentences(text):
        if not re.search(cue, sent, re.I) or re.search(r"\bpoints?\b|\bbonus\b|\bscor\w+", sent, re.I):
            continue
        if re.search(r"(?:full|whole|finished|complete\w*|filled?)\s+(?:horizontal\s+)?row|horizontal\s+row|row\s+of\s+(?:five|5)|line\s+across|across", sent, re.I):
            return "row"
        if re.search(r"vertical|column|line\s+down|\bdown\b", sent, re.I):
            return "column"
        if re.search(r"colou?r", sent, re.I):
            return "color"
    return None


def parse_token_on_floor(text: str) -> Optional[bool]:
    for sent in split_sentences(text):
        if re.search(r"token|marker", sent, re.I) and re.search(r"floor", sent, re.I):
            return True
    return None


def parse_token_starts_next(text: str) -> Optional[bool]:
    for sent in split_sentences(text):
        if re.search(r"token|marker|first[- ]player", sent, re.I) and re.search(
                r"next round|begins the next|starts the next|goes first|start(?:s|ing)? player|first in the next|opening player|round after|opens? (?:the )?next|starts? with", sent, re.I):
            return True
    return None


def parse_isolated_score(text: str) -> Optional[int]:
    cue = (r"no\s+neighbo\w*|isolated|alone|by itself|not adjacent|nothing\s+(?:is\s+)?(?:touching|adjacent|touches)|"
           r"no\s+adjacent|has no adjacent|touch\w*\s+nothing|not\s+touch\w*")
    for sent in split_sentences(text):
        if re.search(cue, sent, re.I):
            m = re.search(rf"({_NUM})\s+points?", sent, re.I)
            if m:
                return to_int(m.group(1))
            m = re.search(rf"(?:scores?|worth|gets?|earns?|gains?)\s+(?:just\s+|only\s+)?({_NUM})\b", sent, re.I)
            if m:
                return to_int(m.group(1))
    return None


def parse_both_directions(text: str) -> Optional[bool]:
    horizontal = re.search(r"horizontal|same\s+row|across|in\s+the\s+row|row\b|left[- ]right|left\s+to\s+right|sideways", text, re.I)
    vertical = re.search(r"vertical|same\s+column|down|in\s+the\s+column|column\b|up[- ]down|top\s+to\s+bottom", text, re.I)
    related = re.search(r"chain|line|neighbo\w*|adjacent|connected|group|touch\w*|tiles?", text, re.I)
    return True if horizontal and vertical and related else None


# field -> (retrieval query, parser). A passage is only parsed for a field if it also matches GATE[field].
SPEC: Dict[str, Tuple[str, Callable[[str], object]]] = {
    "colors": ("tile colours blue yellow red black white bag", parse_colors),
    "tiles_per_color": ("how many tiles of each colour in the bag total", parse_tiles_per_color),
    "tiles_per_factory": ("tiles drawn from the bag placed on each factory display start of round", parse_tiles_per_factory),
    "factories_by_players": ("number of factory displays for 2 3 4 players", parse_factories),
    "pattern_capacities": ("pattern lines hold how many tiles from top line to bottom line", parse_pattern_capacities),
    "floor_penalties": ("floor line penalty points each space left to right", parse_floor_penalties),
    "row_bonus": ("end of game bonus points completed horizontal row", lambda t: parse_bonus(t, "row")),
    "column_bonus": ("end of game bonus points completed vertical column", lambda t: parse_bonus(t, "column")),
    "color_bonus": ("end of game bonus points colour all five tiles on the wall", lambda t: parse_bonus(t, "color")),
    "wall_first_row": ("wall first row colour order left to right", parse_wall_first_row),
    "wall_shift": ("wall each row shifted places right wrapping no colour repeats", parse_wall_shift),
    "game_end_trigger": ("game ends finishes when a player completes row", parse_end_trigger),
    "token_on_floor": ("first player token starting token floor line penalty", parse_token_on_floor),
    "token_starts_next_round": ("player who took the starting token begins next round", parse_token_starts_next),
    "isolated_tile_score": ("tile scoring no neighbours isolated tile points", parse_isolated_score),
    "scores_both_directions": ("newly placed tile scores horizontal and vertical connected chain", parse_both_directions),
}



GATE: Dict[str, str] = {
    "colors": r"colou?r|hue|tile",
    "tiles_per_color": r"colou?r|hue",
    "tiles_per_factory": r"factor|display",
    "factories_by_players": r"factor|display",
    "pattern_capacities": r"pattern|staircase|capacit|lines?\b|rows?\b",
    "floor_penalties": r"floor|penalt",
    "row_bonus": r"row",
    "column_bonus": r"column|vertical|line",
    "color_bonus": r"colou?r|hue|set",
    "wall_first_row": r"wall|row",
    "wall_shift": r"row|wall|pattern",
    "game_end_trigger": r"end|final|last|over|finish|trigger",
    "token_on_floor": r"token|marker",
    "token_starts_next_round": r"token|marker",
    "isolated_tile_score": r"neighbo|adjacent|alone|isolated|touch|itself",
    "scores_both_directions": r"horizontal|row|column|vertical",
}

# extra retrieval terms: rulebooks phrase the same rule in many ways
SYNONYMS: Dict[str, str] = {
    "floor_penalties": "penalties cost lose slot space minus negative",
    "row_bonus": "bonus extra earn apiece each full finished rows",
    "column_bonus": "bonus extra earn apiece each full finished columns vertical",
    "color_bonus": "bonus extra earn apiece each colour set completed",
    "wall_shift": "offset rotated moved slides slips step square position",
    "game_end_trigger": "last round final round triggered over finished completes fills",
    "scores_both_directions": "neighbouring adjacent same row same column group chain",
    "isolated_tile_score": "nothing touches alone adjacent earns",
    "tiles_per_factory": "receives gets draw blindly random",
    "tiles_per_color": "every supply colour by colour",
    "factories_by_players": "when play game needs lay out",
    "pattern_capacities": "staircase room sizes lines",
    "token_on_floor": "marker start drop lay",
    "token_starts_next_round": "marker first player plays first following",
}

MERGE_FIELDS = {"factories_by_players"}


class PatternExtractor:
    """Retrieve top passages per rule and parse them with field-specific parsers."""

    def __init__(self, k: int = 12):
        self.k = k

    def extract(self, text: str) -> Tuple[RuleSet, Dict[str, str]]:
        retriever = Retriever(chunk(text))
        rs, evidence = RuleSet(), {}
        for name, (query, parser) in SPEC.items():
            if name in MERGE_FIELDS:       # facts spread over several passages: combine them
                merged: Dict[int, int] = {}
                for hit in retriever.query(query + " " + SYNONYMS.get(name, ""), self.k):
                    if not re.search(GATE[name], hit.text, re.I):
                        continue
                    for key, val in (parser(hit.text) or {}).items():
                        merged.setdefault(key, val)
                        evidence.setdefault(name, hit.text)
                if merged:
                    setattr(rs, name, dict(sorted(merged.items())))
                continue
            for hit in retriever.query(query + " " + SYNONYMS.get(name, ""), self.k):
                if not re.search(GATE[name], hit.text, re.I):
                    continue
                value = parser(hit.text)
                if value is not None:
                    setattr(rs, name, value)
                    evidence[name] = hit.text
                    break
        return rs, evidence


class LLMExtractor:
    """Same retrieval, but a language model reads the passages and returns JSON.

    ``complete`` is any callable ``(system, user) -> str``; ``anthropic_complete`` builds one for the
    Anthropic API. Not benchmarked live (no API key in the development environment).
    """

    SYSTEM = ("You extract board-game rules into JSON. Use only the passages provided. "
              "Reply with a single JSON object whose keys are exactly: " + ", ".join(FIELDS) +
              ". Use null for anything the passages do not state. floor_penalties are negative integers in "
              "order; factories_by_players maps player count to factory count; wall_shift is +1 for "
              "'shifted one place right'; game_end_trigger is 'row', 'column' or 'color'.")

    def __init__(self, complete: Callable[[str, str], str], k: int = 3):
        self.complete = complete
        self.k = k

    def extract(self, text: str) -> Tuple[RuleSet, Dict[str, str]]:
        retriever = Retriever(chunk(text))
        seen: Dict[str, str] = {}
        for name, (query, _) in SPEC.items():
            for hit in retriever.query(query + " " + SYNONYMS.get(name, ""), self.k):
                seen.setdefault(hit.text, name)
        passages = "\n".join(f"- {t}" for t in seen)
        raw = self.complete(self.SYSTEM, f"Passages:\n{passages}\n\nReturn the JSON object.")
        data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        rs = RuleSet()
        for name in FIELDS:
            v = data.get(name)
            if name == "factories_by_players" and isinstance(v, dict):
                v = {int(a): int(b) for a, b in v.items()}
            setattr(rs, name, v)
        return rs, dict(seen)


def anthropic_complete(model: str = "claude-haiku-5-5", max_tokens: int = 1024) -> Callable[[str, str], str]:
    """Build a ``complete`` function backed by the Anthropic API (needs ANTHROPIC_API_KEY)."""
    import anthropic

    client = anthropic.Anthropic()

    def complete(system: str, user: str) -> str:
        msg = client.messages.create(model=model, max_tokens=max_tokens, system=system,
                                     messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    return complete
