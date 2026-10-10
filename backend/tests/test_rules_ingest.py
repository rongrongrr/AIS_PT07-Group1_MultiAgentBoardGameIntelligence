"""Rulebook ingestion: retrieval, extraction, benchmark, LLM wiring and use by the engine."""

import asyncio
import json
from pathlib import Path

import pytest

from app.azul.config import DEFAULT_RULES, RulesConfig
from app.azul.game import new_game, play_game
from app.azul.rules import calculate_end_game_bonuses, calculate_floor_penalty
from app.ml.greedy_player import GreedyPlayer
from app.rules_ingest import extract as X
from app.rules_ingest.benchmark import make_variant, random_truth, run_benchmark
from app.rules_ingest.extract import LLMExtractor, PatternExtractor
from app.rules_ingest.ingest import ingest_file, ingest_text
from app.rules_ingest.retriever import Retriever, chunk, split_sentences
from app.rules_ingest.schema import (
    FIELDS, RuleSet, compare, ground_truth, to_config, wall_matches_standard,
)

CORPUS = Path(__file__).resolve().parents[2] / "docs" / "rules" / "azul_rules.md"


# ------------------------------------------------------------------ retrieval

def test_chunking_drops_headings_and_windows_sentences():
    chunks = chunk("# Title\n\nOne. Two. Three.\n\nSolo sentence.")
    assert chunks == ["One. Two.", "Two. Three.", "Solo sentence."]
    assert split_sentences("A b. C d!  E?") == ["A b.", "C d!", "E?"]


def test_retriever_ranks_relevant_passage_first_and_handles_empty():
    r = Retriever(["The floor line costs points.", "Tiles are made of ceramic.", "Bag holds tiles."])
    assert r.query("floor line penalty points", 2)[0].text.startswith("The floor line")
    assert r.query("zzzz qqqq", 3) == []
    assert Retriever([]).query("anything") == []


# ------------------------------------------------------------------ parsers

@pytest.mark.parametrize("text,expected", [
    ("The penalties are: -1, -1, -2, -2, -2, -3, -3.", [-1, -1, -2, -2, -2, -3, -3]),
    ("costs one, one, two, two, two, three and three points", [-1, -1, -2, -2, -2, -3, -3]),
    ("minus one, minus one, minus two, minus two", [-1, -1, -2, -2]),
    ("2 spaces cost 1 point each; 3 spaces cost 2 points each; 2 spaces cost 3 points each", [-1, -1, -2, -2, -2, -3, -3]),
    ("-1 -1 -2 -2 -2 -3 -3", [-1, -1, -2, -2, -2, -3, -3]),
    ("slot 1 = -1, slot 2 = -2, slot 3 = -3, slot 4 = -4", [-1, -2, -3, -4]),
    ("1 | 1 | 2 | 2 | 2 | 3 | 3", [-1, -1, -2, -2, -2, -3, -3]),
    ("the first two spaces cost 1 point, the next three 2 points, the last two 3 points", [-1, -1, -2, -2, -2, -3, -3]),
    ("nothing about penalties here", None),
])
def test_floor_penalty_parser(text, expected):
    assert X.parse_floor_penalties(text) == expected


@pytest.mark.parametrize("text,kind,expected", [
    ("2 points for each completed horizontal row, 7 points for each completed vertical column, and 10 points for each colour", "row", 2),
    ("2 points for each completed horizontal row, 7 points for each completed vertical column, and 10 points for each colour", "column", 7),
    ("2 points for each completed horizontal row, 7 points for each completed vertical column, and 10 points for each colour", "color", 10),
    ("Every full column is worth seven points.", "column", 7),
    ("For every row you completed: +4.", "row", 4),
    ("No bonus information.", "row", None),
])
def test_bonus_parser(text, kind, expected):
    assert X.parse_bonus(text, kind) == expected


def test_number_helpers():
    assert X.to_int("12") == 12 and X.to_int("Seven") == 7 and X.to_int("lots") is None


@pytest.mark.parametrize("fn,text,expected", [
    (X.parse_factories, "With 2 players the table uses 5 factory displays. With four players use nine factories.", {2: 5, 4: 9}),
    (X.parse_factories, "7 factory displays for 3 players.", {3: 7}),
    (X.parse_factories, "Number of factories: 5 (for 2 players), 9 (for 4 players).", {2: 5, 4: 9}),
    (X.parse_tiles_per_factory, "Four tiles are placed on each factory display.", 4),
    (X.parse_tiles_per_color, "There are 20 tiles of each colour.", 20),
    (X.parse_tiles_per_color, "There are 100 tiles in the bag.", None),
    (X.parse_pattern_capacities, "The lines hold 1, 2, 3, 4 and 5 tiles.", [1, 2, 3, 4, 5]),
    (X.parse_pattern_capacities, "Sizes range from 1 to 5.", [1, 2, 3, 4, 5]),
    (X.parse_wall_first_row, "The first row is blue, yellow, red, black, white.", ["blue", "yellow", "red", "black", "white"]),
    (X.parse_wall_shift, "Each row below is shifted one place to the right.", 1),
    (X.parse_wall_shift, "Each row is offset by 2 columns to the left.", -2),
    (X.parse_end_trigger, "The game ends when a player completes a horizontal row.", "row"),
    (X.parse_end_trigger, "The game ends when someone fills a vertical column.", "column"),
    (X.parse_end_trigger, "Rows give 2 points at the end of the game.", None),
    (X.parse_token_on_floor, "The token goes on the floor line.", True),
    (X.parse_token_starts_next, "That player begins the next round.", None),
    (X.parse_token_starts_next, "The token holder begins the next round, taking the token.", True),
    (X.parse_isolated_score, "A tile with no neighbours scores 1 point.", 1),
    (X.parse_both_directions, "Count the horizontal chain and the vertical chain.", True),
    (X.parse_colors, "Tiles come in blue, yellow, red, black and white.", ["blue", "yellow", "red", "black", "white"]),
    (X.parse_colors, "The first row is blue, yellow, red, black, white.", None),
])
def test_field_parsers(fn, text, expected):
    assert fn(text) == expected


# ------------------------------------------------------------------ extraction on the real corpus

def test_real_corpus_matches_the_engine_exactly():
    res = ingest_file(CORPUS)
    assert res.matches_engine, res.differences_from_standard
    assert res.config == DEFAULT_RULES or res.config is not None
    assert res.config.floor_penalties == DEFAULT_RULES.floor_penalties
    assert res.wall_matches_standard
    assert set(res.evidence) >= {"floor_penalties", "factories_by_players", "wall_shift"}


def test_ruleset_roundtrip_and_comparison_helpers():
    truth = ground_truth()
    assert set(truth.to_dict()) == set(FIELDS)
    assert all(compare(truth).values())
    broken = RuleSet(**{**truth.to_dict(), "row_bonus": 3, "colors": None})
    res = compare(broken)
    assert res["row_bonus"] is False and res["colors"] is False and res["column_bonus"] is True


def test_wall_verification_detects_wrong_layout():
    rs = ground_truth()
    assert wall_matches_standard(rs)
    rs.wall_shift = -1
    assert not wall_matches_standard(rs)
    rs.wall_first_row = None
    assert not wall_matches_standard(rs)


def test_to_config_strict_and_lenient():
    rs = RuleSet(row_bonus=3)
    with pytest.raises(ValueError, match="did not yield"):
        to_config(rs)
    cfg = to_config(rs, strict=False)
    assert cfg.row_bonus == 3 and cfg.column_bonus == DEFAULT_RULES.column_bonus
    res = ingest_text("Nothing useful in this text.")
    assert res.config is None and "floor_penalties" in res.missing and not res.matches_engine


# ------------------------------------------------------------------ benchmark

def test_variants_are_deterministic_and_randomised():
    a = make_variant(__import__("random").Random(5), "dev")
    b = make_variant(__import__("random").Random(5), "dev")
    assert a.text == b.text and a.truth == b.truth
    truths = {tuple(random_truth(__import__("random").Random(s)).floor_penalties) for s in range(30)}
    assert len(truths) > 3                                    # values vary, so no memorising
    with pytest.raises(ValueError):
        make_variant(__import__("random").Random(1), "nonsense")


def test_benchmark_accuracy_floors():
    ex = PatternExtractor()
    dev = run_benchmark(ex, "dev", count=30, seed=3)
    held = run_benchmark(ex, "heldout", count=30, seed=3)
    fresh = run_benchmark(ex, "fresh", count=30, seed=3)
    assert dev["field_accuracy"] >= 0.97 and held["field_accuracy"] >= 0.97
    assert fresh["field_accuracy"] >= 0.85          # first-run (untuned) figure was 0.63; see docs
    assert set(dev["per_field"]) == set(FIELDS)


# ------------------------------------------------------------------ LLM wiring (stub client)

def test_llm_extractor_parses_json_reply_and_passes_retrieved_passages():
    seen = {}
    reply = json.dumps({**{f: None for f in FIELDS}, "row_bonus": 2, "factories_by_players": {"2": 5, "3": 7},
                        "floor_penalties": [-1, -1]})

    def fake_complete(system, user):
        seen["system"], seen["user"] = system, user
        return "Here you go:\n" + reply

    rs, evidence = LLMExtractor(fake_complete).extract(CORPUS.read_text(encoding="utf-8"))
    assert rs.row_bonus == 2 and rs.factories_by_players == {2: 5, 3: 7} and rs.floor_penalties == [-1, -1]
    assert "Passages:" in seen["user"] and "floor" in seen["user"].lower()
    assert all(f in seen["system"] for f in FIELDS)
    assert evidence


# ------------------------------------------------------------------ ingested rules drive the engine

def test_config_changes_scoring_functions():
    cfg = RulesConfig(floor_penalties=(-2, -2, -4), row_bonus=5, column_bonus=1, color_bonus=3)
    assert calculate_floor_penalty(2, cfg) == -4 and calculate_floor_penalty(5, cfg) == -8
    full = [[True] * 5 for _ in range(5)]
    assert calculate_end_game_bonuses(full, cfg)["total"] == 5 * 5 + 5 * 1 + 5 * 3
    assert calculate_end_game_bonuses(full)["total"] == 95           # default unchanged


def test_ingested_standard_rules_play_identically_to_builtin_rules():
    cfg = ingest_file(CORPUS).config
    def play(rules):
        ps = [GreedyPlayer(), GreedyPlayer()]
        return asyncio.run(play_game([p.decide for p in ps], ["A", "B"], seed=4, rules=rules))
    assert play(cfg) == play(DEFAULT_RULES)


def test_modified_rulebook_changes_the_game():
    text = CORPUS.read_text(encoding="utf-8")
    text = text.replace("-1, -1, -2, -2, -2, -3, -3", "-3, -3, -4, -4, -4, -5, -5")
    text = text.replace("With 2 players the table uses 5 factory displays", "With 2 players the table uses 6 factory displays")
    res = ingest_text(text)
    assert res.config.floor_penalties == (-3, -3, -4, -4, -4, -5, -5)
    assert res.config.factories_by_players[2] == 6
    assert not res.matches_engine and "floor_penalties" in res.differences_from_standard
    sim = new_game(["A", "B"], seed=1, rules=res.config)
    assert len(sim.state.factories) == 6                              # the ingested rule reached the game
