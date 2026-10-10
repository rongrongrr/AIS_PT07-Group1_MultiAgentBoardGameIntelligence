"""Rule-extraction benchmark: generated rulebooks with known parameters.

Each rulebook has *randomised* parameter values (penalties, bonuses, tile counts, factory
counts, wall layout...), so an extractor cannot succeed by remembering standard Azul numbers.
Facts are phrased with templates and mixed with distractor sentences (including numbers that are
not rules). Two disjoint template groups exist:

* ``dev``:      the phrasings the parsers were developed against.
* ``fresh``:    a third set written after the parsers were last changed and run once before any
                further tuning; it is the best estimate of how the extractor generalises.
* ``heldout``:  phrasings written separately, deliberately more varied (ordinals, tables,
                pipes, reversed word order). Parsers were not tuned on these before the first run.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable, Dict, List, Tuple

from app.rules_ingest.extract import NUMBER_WORDS
from app.rules_ingest.schema import FIELDS, RuleSet, compare

WORDS = {v: k for k, v in NUMBER_WORDS.items()}
COLORS = ["blue", "yellow", "red", "black", "white"]
ORD = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh"]


def n(v: int, rng: random.Random) -> str:
    return WORDS[v] if v in WORDS and rng.random() < 0.5 else str(v)


def pts(v: int) -> str:
    return "point" if v == 1 else "points"


def oxford(items: List[str], conj: str = "and") -> str:
    return ", ".join(items[:-1]) + f" {conj} " + items[-1]


# --------------------------------------------------------------------------- truth generation

def random_truth(rng: random.Random) -> RuleSet:
    pen = sorted(rng.choice([0, 1, 1, 2, 2, 3, 4]) for _ in range(7))
    players = [2, 3, 4]
    facs = sorted(rng.sample(range(3, 13), 3))
    colors = rng.sample(COLORS, 5)
    return RuleSet(
        colors=colors,
        tiles_per_color=rng.choice([12, 15, 18, 20, 22, 25]),
        tiles_per_factory=rng.choice([3, 4, 5, 6]),
        factories_by_players=dict(zip(players, facs)),
        pattern_capacities=[1, 2, 3, 4, 5],
        floor_penalties=[-p for p in pen],
        row_bonus=rng.randint(1, 9),
        column_bonus=rng.randint(2, 15),
        color_bonus=rng.randint(5, 20),
        wall_first_row=rng.sample(COLORS, 5),
        wall_shift=rng.choice([1, 1, -1, 2]),
        game_end_trigger=rng.choice(["row", "row", "column"]),
        token_on_floor=True,
        token_starts_next_round=True,
        isolated_tile_score=rng.choice([1, 1, 2]),
        scores_both_directions=True,
    )


# --------------------------------------------------------------------------- templates
Template = Callable[[RuleSet, random.Random], str]


def _signed(vals, rng, style):
    ps = [abs(v) for v in vals]
    if style == "digits":
        return ", ".join(f"-{p}" for p in ps)
    if style == "words":
        return ", ".join(f"minus {WORDS[p]}" for p in ps)
    if style == "unsigned":
        return oxford([str(p) for p in ps])
    if style == "slash":
        return " / ".join(str(p) for p in ps)
    if style == "pipe":
        return " | ".join(str(p) for p in ps)
    raise ValueError(style)


def _runs(vals):
    out, cur, count = [], None, 0
    for v in vals:
        if v == cur:
            count += 1
        else:
            if cur is not None:
                out.append((count, cur))
            cur, count = v, 1
    out.append((count, cur))
    return out


DEV: Dict[str, List[Template]] = {
    "colors": [
        lambda t, r: f"There are five colours of tile: {oxford(t.colors)}.",
        lambda t, r: f"Tiles come in five colours: {oxford(t.colors)}.",
        lambda t, r: f"The game has five colours: {', '.join(t.colors)}, all mixed in one bag.".replace(f", {t.colors[-1]}", f" and {t.colors[-1]}"),
    ],
    "tiles_per_color": [
        lambda t, r: f"The bag holds {n(t.tiles_per_color, r)} tiles of each colour.",
        lambda t, r: f"There are {n(t.tiles_per_color, r)} tiles per colour in the bag.",
        lambda t, r: f"Each colour has {n(t.tiles_per_color, r)} tiles in the supply.",
    ],
    "tiles_per_factory": [
        lambda t, r: f"At the start of a round, {n(t.tiles_per_factory, r)} tiles are drawn at random and placed on each factory display.",
        lambda t, r: f"Fill every factory with {n(t.tiles_per_factory, r)} tiles from the bag.",
        lambda t, r: f"Put {n(t.tiles_per_factory, r)} random tiles on each factory display before play begins.",
    ],
    "factories_by_players": [
        lambda t, r: "; ".join(f"with {n(p, r)} players the table uses {n(f, r)} factory displays" for p, f in t.factories_by_players.items()).capitalize() + ".",
        lambda t, r: " ".join(f"For {p} players, set out {n(f, r)} factories." for p, f in t.factories_by_players.items()),
        lambda t, r: " ".join(f"{p} players: {f} factory displays." for p, f in t.factories_by_players.items()),
    ],
    "pattern_capacities": [
        lambda t, r: "The pattern lines hold 1, 2, 3, 4 and 5 tiles from top to bottom.",
        lambda t, r: "Pattern lines range from one to five tiles in size, top line smallest.",
        lambda t, r: "There are five pattern lines which hold one, two, three, four and five tiles.",
    ],
    "floor_penalties": [
        lambda t, r: f"Reading the floor line left to right, the penalties are: {_signed(t.floor_penalties, r, 'digits')}.",
        lambda t, r: f"The seven floor spaces cost, in order, {_signed(t.floor_penalties, r, 'unsigned')} points.",
        lambda t, r: "On the floor, " + "; ".join(f"{n(c, r)} spaces cost {n(abs(v), r)} {pts(abs(v))} each" for c, v in _runs(t.floor_penalties)) + ".",
    ],
    "row_bonus": [
        lambda t, r: f"At the end, each completed horizontal row gives {n(t.row_bonus, r)} {pts(t.row_bonus)}.",
        lambda t, r: f"{n(t.row_bonus, r)} bonus {pts(t.row_bonus)} for each complete row.",
        lambda t, r: f"A finished horizontal row is worth {n(t.row_bonus, r)} {pts(t.row_bonus)}.",
    ],
    "column_bonus": [
        lambda t, r: f"Each completed vertical column gives {n(t.column_bonus, r)} points.",
        lambda t, r: f"{n(t.column_bonus, r)} bonus points for every full column.",
        lambda t, r: f"A finished vertical column is worth {n(t.column_bonus, r)} points.",
    ],
    "color_bonus": [
        lambda t, r: f"Each colour that has all five of its tiles on the wall earns {n(t.color_bonus, r)} points.",
        lambda t, r: f"{n(t.color_bonus, r)} points for each colour completed on the wall.",
        lambda t, r: f"A colour with every tile placed on the wall is worth {n(t.color_bonus, r)} points.",
    ],
    "wall_first_row": [
        lambda t, r: f"The first row of the wall reads {', '.join(t.wall_first_row)} from left to right.",
        lambda t, r: f"In the first row the colours are arranged {oxford(t.wall_first_row)}.",
        lambda t, r: f"The top row of the wall is {', '.join(t.wall_first_row)}.",
    ],
    "wall_shift": [
        lambda t, r: f"Each following row is shifted {n(abs(t.wall_shift), r)} {'place' if abs(t.wall_shift)==1 else 'places'} to the {'right' if t.wall_shift > 0 else 'left'}, wrapping around.",
        lambda t, r: f"Every row below is the previous row shifted {n(abs(t.wall_shift), r)} {'space' if abs(t.wall_shift)==1 else 'spaces'} {'right' if t.wall_shift > 0 else 'left'}.",
        lambda t, r: f"Rows are offset by {n(abs(t.wall_shift), r)} {'column' if abs(t.wall_shift)==1 else 'columns'} to the {'right' if t.wall_shift > 0 else 'left'} each time.",
    ],
    "game_end_trigger": [
        lambda t, r: f"The game ends at the end of the round in which a player completes a {_trigger_word(t.game_end_trigger)}.",
        lambda t, r: f"The final round is triggered when someone completes a {_trigger_word(t.game_end_trigger)}.",
        lambda t, r: f"Play finishes after the round where a player fills a {_trigger_word(t.game_end_trigger)}.",
    ],
    "token_on_floor": [
        lambda t, r: "Whoever first takes from the centre also takes the starting token and puts it on their floor line.",
        lambda t, r: "The token goes on the floor line of the player who takes it.",
        lambda t, r: "Taking the starting token means placing it on the floor line.",
    ],
    "token_starts_next_round": [
        lambda t, r: "The player holding the starting token begins the next round.",
        lambda t, r: "Whoever took the token goes first in the next round.",
        lambda t, r: "The token holder starts the next round.",
    ],
    "isolated_tile_score": [
        lambda t, r: f"A tile with no neighbours scores {n(t.isolated_tile_score, r)} {pts(t.isolated_tile_score)}.",
        lambda t, r: f"An isolated tile is worth {n(t.isolated_tile_score, r)} {pts(t.isolated_tile_score)}.",
        lambda t, r: f"A tile that stands alone scores {n(t.isolated_tile_score, r)} {pts(t.isolated_tile_score)}.",
    ],
    "scores_both_directions": [
        lambda t, r: "A placed tile scores the connected horizontal chain plus the connected vertical chain.",
        lambda t, r: "Count the adjacent tiles in the horizontal line and in the vertical line through the new tile.",
        lambda t, r: "Add up the horizontal and vertical groups of connected tiles that include the new tile.",
    ],
}


def _trigger_word(kind: str) -> str:
    return {"row": "horizontal row", "column": "vertical column", "color": "colour set"}[kind]


HELDOUT: Dict[str, List[Template]] = {
    "colors": [
        lambda t, r: f"You will find {oxford(t.colors)} tiles in the bag - five colours altogether.",
        lambda t, r: f"Colours used: {' / '.join(t.colors)}.",
        lambda t, r: f"Every tile is one of five hues ({', '.join(t.colors)}).",
    ],
    "tiles_per_color": [
        lambda t, r: f"Shuffle all the tiles into the bag; there are {n(t.tiles_per_color, r)} in every colour.",
        lambda t, r: f"{n(t.tiles_per_color, r).capitalize()} tiles of every colour make up the supply.",
        lambda t, r: f"Colour by colour, the supply contains {n(t.tiles_per_color, r)} tiles.",
    ],
    "tiles_per_factory": [
        lambda t, r: f"Each factory display receives {n(t.tiles_per_factory, r)} tiles drawn blindly from the bag.",
        lambda t, r: f"Prepare the factories: draw tiles blindly, {n(t.tiles_per_factory, r)} to each display.",
        lambda t, r: f"Every display gets {n(t.tiles_per_factory, r)} tiles at the beginning of each round.",
    ],
    "factories_by_players": [
        lambda t, r: "Factory displays needed: " + ", ".join(f"{n(f, r)} when {p} play" for p, f in t.factories_by_players.items()).replace(" play", " players") + ".",
        lambda t, r: " ".join(f"A {p}-player game needs {n(f, r)} factory displays." for p, f in t.factories_by_players.items()),
        lambda t, r: " ".join(f"Lay out {n(f, r)} factories if {n(p, r)} players take part." for p, f in t.factories_by_players.items()),
    ],
    "pattern_capacities": [
        lambda t, r: "Starting from the top, the five pattern lines have room for one tile, then two, then three, then four, then five.",
        lambda t, r: "Pattern line sizes grow by one each line, from 1 up to 5.",
        lambda t, r: "The staircase on the left has lines sized 1 - 5.",
    ],
    "floor_penalties": [
        lambda t, r: "Starting from the leftmost slot the penalties are " + ", ".join(f"minus {WORDS[abs(v)]} for the {ORD[i]}" for i, v in enumerate(t.floor_penalties)) + ".",
        lambda t, r: f"Floor penalties (left to right): {_signed(t.floor_penalties, r, 'pipe')}.",
        lambda t, r: f"Penalty per floor slot, leftmost first: {_signed(t.floor_penalties, r, 'slash')}.",
    ],
    "row_bonus": [
        lambda t, r: f"When the game is over, finished rows add {n(t.row_bonus, r)} {pts(t.row_bonus)} apiece.",
        lambda t, r: f"Horizontal rows that are full earn you {n(t.row_bonus, r)} extra {pts(t.row_bonus)} each.",
        lambda t, r: f"For every row you completed: +{t.row_bonus}.",
    ],
    "column_bonus": [
        lambda t, r: f"Full columns add {n(t.column_bonus, r)} points apiece at game end.",
        lambda t, r: f"Vertical lines that are complete earn you {n(t.column_bonus, r)} extra points each.",
        lambda t, r: f"For every column you completed: +{t.column_bonus}.",
    ],
    "color_bonus": [
        lambda t, r: f"If all five tiles of a single colour are on your wall, add {n(t.color_bonus, r)} points.",
        lambda t, r: f"Colour sets completed on the wall are rewarded with {n(t.color_bonus, r)} points each.",
        lambda t, r: f"For every colour you completed: +{t.color_bonus}.",
    ],
    "wall_first_row": [
        lambda t, r: f"Lay the wall out as follows: left to right, row one is {' then '.join(t.wall_first_row)}.",
        lambda t, r: f"Row 1 of the wall (from the left): {' | '.join(t.wall_first_row)}.",
        lambda t, r: f"Begin with {oxford(t.wall_first_row)} across the first row.",
    ],
    "wall_shift": [
        lambda t, r: f"Each lower row slides {n(abs(t.wall_shift), r)} step{'s' if abs(t.wall_shift) != 1 else ''} {'rightwards' if t.wall_shift > 0 else 'leftwards'} compared with the one above.",
        lambda t, r: f"Moving down a row, everything is moved {n(abs(t.wall_shift), r)} {'square' if abs(t.wall_shift)==1 else 'squares'} to the {'right' if t.wall_shift > 0 else 'left'}.",
        lambda t, r: f"The pattern is rotated {n(abs(t.wall_shift), r)} {'position' if abs(t.wall_shift)==1 else 'positions'} {'right' if t.wall_shift > 0 else 'left'} on every row.",
    ],
    "game_end_trigger": [
        lambda t, r: f"As soon as any wall has a full {_trigger_word2(t.game_end_trigger)}, this is the last round.",
        lambda t, r: f"Once a player has finished a whole {_trigger_word2(t.game_end_trigger)}, the game is over after that round.",
        lambda t, r: f"The end of the game is triggered by a completed {_trigger_word2(t.game_end_trigger)} on any wall.",
    ],
    "token_on_floor": [
        lambda t, r: "The player who claims the start marker from the centre must lay it on the first floor space.",
        lambda t, r: "That marker is then dropped onto the floor line, where it costs points like a tile.",
        lambda t, r: "Floor line, first space: the token goes there when someone takes it.",
    ],
    "token_starts_next_round": [
        lambda t, r: "Next round, the person who picked up the marker plays first.",
        lambda t, r: "Having taken the starting token, that player starts the following round, i.e. the next round.",
        lambda t, r: "Whoever has the marker at the end of the round is first player in the next round.",
    ],
    "isolated_tile_score": [
        lambda t, r: f"If nothing touches the new tile, it earns just {n(t.isolated_tile_score, r)} {pts(t.isolated_tile_score)}.",
        lambda t, r: f"A tile placed with no adjacent tiles earns {n(t.isolated_tile_score, r)} {pts(t.isolated_tile_score)}.",
        lambda t, r: f"No neighbours at all: the tile scores {n(t.isolated_tile_score, r)}.",
    ],
    "scores_both_directions": [
        lambda t, r: "Score the new tile's horizontal group of connected tiles and its vertical group as well.",
        lambda t, r: "Neighbouring tiles in the same row and in the same column both count towards the score.",
        lambda t, r: "The tile scores once for the connected chain across the row and once for the chain down the column.",
    ],
}


def _trigger_word2(kind: str) -> str:
    return {"row": "horizontal row", "column": "vertical column", "color": "colour group"}[kind]


FRESH: Dict[str, List[Template]] = {
    "colors": [
        lambda t, r: f"Our set has five hues - {', '.join(t.colors[:4])} and {t.colors[4]}.",
        lambda t, r: f"Tile colours -> {'; '.join(t.colors)}.",
        lambda t, r: f"The tiles are coloured {', '.join(t.colors[:4])}, and {t.colors[4]}.",
    ],
    "tiles_per_color": [
        lambda t, r: f"{n(t.tiles_per_color, r).capitalize()} of each colour go into the bag.",
        lambda t, r: f"Count out {n(t.tiles_per_color, r)} tiles for every colour before shuffling.",
        lambda t, r: f"The supply is {n(t.tiles_per_color, r)} tiles deep per colour.",
    ],
    "tiles_per_factory": [
        lambda t, r: f"Setup: deal {n(t.tiles_per_factory, r)} tiles from the bag to every factory display.",
        lambda t, r: f"Each factory display starts the round with {n(t.tiles_per_factory, r)} tiles on it.",
        lambda t, r: f"Factory displays hold {n(t.tiles_per_factory, r)} tiles apiece at the start of a round.",
    ],
    "factories_by_players": [
        lambda t, r: " ".join(f"In a {p}-player session, you need {f} factory displays on the table." for p, f in t.factories_by_players.items()),
        lambda t, r: "Number of factories: " + ", ".join(f"{f} (for {p} players)" for p, f in t.factories_by_players.items()) + ".",
        lambda t, r: " ".join(f"{p} participants \u2192 {f} factory displays." for p, f in t.factories_by_players.items()),
    ],
    "pattern_capacities": [
        lambda t, r: "Line capacities: one, two, three, four, five.",
        lambda t, r: "The staircase has rows with 1, 2, 3, 4, 5 spots.",
        lambda t, r: "Each pattern line is one tile longer than the line above it, beginning with a single tile and ending with five.",
    ],
    "floor_penalties": [
        lambda t, r: "The floor line's penalty spaces, left to right, read " + " ".join(f"-{abs(v)}" for v in t.floor_penalties) + ".",
        lambda t, r: "Penalties: " + ", ".join(f"slot {i + 1} = -{abs(v)}" for i, v in enumerate(t.floor_penalties)) + ".",
        lambda t, r: "A tile in " + ", ".join(f"slot {WORDS[i + 1]} costs {WORDS[abs(v)]}" for i, v in enumerate(t.floor_penalties)) + ".",
    ],
    "row_bonus": [
        lambda t, r: f"Each full horizontal line across the wall brings {n(t.row_bonus, r)} {pts(t.row_bonus)} at the end.",
        lambda t, r: f"Bonus for rows is {n(t.row_bonus, r)} {pts(t.row_bonus)} per row.",
        lambda t, r: f"Every row you complete across the wall is rewarded with {n(t.row_bonus, r)} extra {pts(t.row_bonus)} when the game ends.",
    ],
    "column_bonus": [
        lambda t, r: f"Each full vertical line down the wall brings {n(t.column_bonus, r)} points at the end.",
        lambda t, r: f"Bonus for columns is {n(t.column_bonus, r)} points per column.",
        lambda t, r: f"Every column you complete down the wall is rewarded with {n(t.column_bonus, r)} extra points when the game ends.",
    ],
    "color_bonus": [
        lambda t, r: f"Having all five tiles of one colour on your wall is worth {n(t.color_bonus, r)} points.",
        lambda t, r: f"Bonus for colour sets is {n(t.color_bonus, r)} points per set.",
        lambda t, r: f"Every colour you manage to complete on the wall is rewarded with {n(t.color_bonus, r)} extra points when the game ends.",
    ],
    "wall_first_row": [
        lambda t, r: f"Wall setup, row 1: {' '.join(t.wall_first_row)} (read left to right).",
        lambda t, r: f"The upper row of the wall has the colours in this order: {', '.join(t.wall_first_row)}.",
        lambda t, r: f"Place the colours in the order {', '.join(t.wall_first_row)} along the first row.",
    ],
    "wall_shift": [
        lambda t, r: f"Below it, every row steps {n(abs(t.wall_shift), r)} to the {'right' if t.wall_shift > 0 else 'left'} of the row above.",
        lambda t, r: f"Each subsequent row is a copy of the one above displaced by {n(abs(t.wall_shift), r)} to the {'right' if t.wall_shift > 0 else 'left'}.",
        lambda t, r: f"Every row starts {n(abs(t.wall_shift), r)} {'position' if abs(t.wall_shift)==1 else 'positions'} further {'right' if t.wall_shift > 0 else 'left'} than the previous one.",
    ],
    "game_end_trigger": [
        lambda t, r: f"Complete a {_fresh_line(t.game_end_trigger)} of five tiles and the game will end once that round concludes.",
        lambda t, r: f"Game end: the moment somebody has a full {_fresh_line(t.game_end_trigger)} of five, finish the round and the game is over.",
        lambda t, r: f"The game stops after the round in which a wall gets a finished {_fresh_line(t.game_end_trigger)}.",
    ],
    "token_on_floor": [
        lambda t, r: "The first-player marker is dropped onto your floor line when you grab it.",
        lambda t, r: "Grabbing the start token puts it in the first floor slot.",
        lambda t, r: "Whoever picks up the starting token must add it to their floor line.",
    ],
    "token_starts_next_round": [
        lambda t, r: "Taking the token makes you the opening player for the round after.",
        lambda t, r: "The next round starts with the token holder.",
        lambda t, r: "The token's owner opens the next round.",
    ],
    "isolated_tile_score": [
        lambda t, r: f"A lone tile, touching nothing, is worth {n(t.isolated_tile_score, r)} {pts(t.isolated_tile_score)}.",
        lambda t, r: f"When a tile sits alone with no tiles next to it, you gain {n(t.isolated_tile_score, r)} {pts(t.isolated_tile_score)}.",
        lambda t, r: f"Tiles with nothing adjacent score {n(t.isolated_tile_score, r)}.",
    ],
    "scores_both_directions": [
        lambda t, r: "Look along the row and down the column from the new tile; each connected run counts.",
        lambda t, r: "Add the length of the connected tiles left-right to the length of those up-down.",
        lambda t, r: "The score is the sum of the horizontally connected tiles and the vertically connected tiles.",
    ],
}


def _fresh_line(kind: str) -> str:
    return {"row": "line across", "column": "line down", "color": "colour set"}[kind]


DISTRACTORS = [
    "Azul was designed for 2 to 4 players and takes about 30 to 45 minutes to play.",
    "The box contains 4 player boards, 1 bag and a scoring track that runs from 0 to 100.",
    "The game was published in 2017 and is recommended for ages 8 and up.",
    "Many players enjoy planning several rounds ahead, but flexibility usually wins.",
    "The tiles are inspired by the glazed ceramic tiles of Portuguese palaces.",
    "Keep the bag within reach of the person setting up the factory displays.",
    "A good strategy is to watch what your neighbours collect.",
    "Remember that the scoring track wraps around if you pass 100 points.",
    "There are 5 rows on the wall and each player has exactly one wall.",
    "Younger players may like to team up with an experienced player for the first game.",
    "Some groups agree to play two rounds quickly as a warm-up before the real game.",
    "The score marker starts on 0 and moves forward as points are earned.",
]


@dataclass
class Variant:
    text: str
    truth: RuleSet


def make_variant(rng: random.Random, group: str, distractors: int = 6) -> Variant:
    templates = {"dev": DEV, "heldout": HELDOUT, "fresh": FRESH}.get(group)
    if templates is None:
        raise ValueError(group)
    truth = random_truth(rng)
    facts = [rng.choice(templates[f])(truth, rng) for f in FIELDS]
    paragraphs = facts + rng.sample(DISTRACTORS, distractors)
    rng.shuffle(paragraphs)
    text = "\n\n".join(paragraphs)
    return Variant(text, truth)


def run_benchmark(extractor, group: str, count: int = 100, seed: int = 0) -> Dict:
    """Returns per-field accuracy and fully-correct-rulebook rate."""
    rng = random.Random(seed)
    hits = {f: 0 for f in FIELDS}
    full = 0
    failures: List[Tuple[str, object, object]] = []
    for _ in range(count):
        v = make_variant(rng, group)
        rs, _evidence = extractor.extract(v.text)
        res = compare(rs, v.truth)
        for f, ok in res.items():
            hits[f] += ok
            if not ok and len(failures) < 400:
                failures.append((f, getattr(rs, f), getattr(v.truth, f)))
        full += all(res.values())
    return {
        "group": group, "count": count, "seed": seed,
        "per_field": {f: hits[f] / count for f in FIELDS},
        "field_accuracy": sum(hits.values()) / (count * len(FIELDS)),
        "rulebook_exact": full / count,
        "failures": failures,
    }
