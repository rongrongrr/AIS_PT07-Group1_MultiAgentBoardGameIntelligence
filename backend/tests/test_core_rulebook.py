"""Rule ingestion pipeline tests: retrieval, extraction, verification."""

import copy

import pytest

from tiles.rulebook import (
    RulebookIndex,
    extract_rules_deterministic,
    verify_rules,
)


@pytest.fixture(scope="module")
def index() -> RulebookIndex:
    return RulebookIndex.build()


@pytest.fixture(scope="module")
def specs(index):
    return extract_rules_deterministic(index)


def by_id(specs):
    return {spec.id: spec for spec in specs}


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def test_retrieval_finds_floor_penalty_section(index):
    results = index.search("floor line penalty points", k=3)
    assert results, "no chunks retrieved"
    assert results[0].section == "floor-line"
    assert results[0].score > 0


def test_retrieval_finds_bonus_section(index):
    results = index.search("end of game bonus complete row column color", k=3)
    assert any(c.section == "final-bonuses" for c in results)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def test_extraction_finds_core_rules(specs):
    assert len(specs) >= 10
    ids = set(by_id(specs))
    for expected in (
        "floor_penalties",
        "endgame_bonuses",
        "factory_counts",
        "placement_scoring",
        "wall_duplicate",
        "line_single_color",
        "line_capacity",
    ):
        assert expected in ids, f"missing rule {expected}"


def test_extracted_floor_penalties(specs):
    spec = by_id(specs)["floor_penalties"]
    assert spec.parameters["penalties"] == [-1, -1, -2, -2, -2, -3, -3]
    assert spec.kind == "scoring"
    assert spec.section == "floor-line"


def test_extracted_bonuses(specs):
    spec = by_id(specs)["endgame_bonuses"]
    assert spec.parameters == {"row": 2, "col": 7, "color": 10}


def test_extracted_factory_counts(specs):
    spec = by_id(specs)["factory_counts"]
    assert spec.parameters["factories_by_players"] == {2: 5, 3: 7, 4: 9}


def test_constraint_rules_map_to_engine_predicates(specs):
    mapped = by_id(specs)
    assert mapped["wall_duplicate"].predicate == "wall_slot_open"
    assert mapped["line_single_color"].predicate == "line_color_matches"
    assert mapped["line_capacity"].predicate == "line_has_space"
    assert mapped["draft_take_all"].predicate == "source_has_color"


# ---------------------------------------------------------------------------
# Verification (the accuracy benchmark)
# ---------------------------------------------------------------------------


def test_verification_accuracy_is_perfect(specs):
    report = verify_rules(specs)
    assert not report.skipped, f"unchecked rules: {report.skipped}"
    assert report.mismatches == [], report.summary_table()
    assert report.accuracy == 1.0


def test_verification_flags_corrupted_rule(specs):
    corrupted = copy.deepcopy(specs)
    spec = by_id(corrupted)["endgame_bonuses"]
    spec.parameters["col"] = 8  # wrong: engine awards 7 per column
    report = verify_rules(corrupted)
    assert report.accuracy < 1.0
    assert any(c.rule_id == "endgame_bonuses" for c in report.mismatches)
    detail = next(c for c in report.mismatches if c.rule_id == "endgame_bonuses")
    assert "8" in detail.detail and "7" in detail.detail
