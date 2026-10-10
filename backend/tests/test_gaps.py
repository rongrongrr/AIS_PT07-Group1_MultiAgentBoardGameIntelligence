"""Remaining edge cases in rules, game engine, archetypes, analyzers and adaptive player."""

import asyncio
import json
import random
import sys
from pathlib import Path

import numpy as np
import pytest

from tiles.azul import game as G
from tiles.azul import rules as R
from tiles.azul import scoring
from tiles.ml import adaptive_player as AP
from tiles.ml.analyzers import ArchetypeProfileAnalyzer, BasicProfileAnalyzer, analyzer_registry
from tiles.ml.archetypes import (
    FEATURE_NAMES, ArchetypeClassifier, ArchetypeModel, extract_features,
)
from tiles.models.schemas import (
    DestinationType, GameAction, GameStateData, PlayerState, SourceType, TileColor,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import train_archetypes as ta  # noqa: E402


# ----------------------------------------------------------------- rules

def test_scoring_module_reexports_rules():
    assert scoring.score_tile_placement is R.score_tile_placement
    assert scoring.FLOOR_PENALTIES == R.FLOOR_PENALTIES


def test_get_factory_tiles_bounds():
    s = GameStateData(factories=[[TileColor.RED, TileColor.BLUE]])
    assert R.get_factory_tiles(s, 0) == [TileColor.RED, TileColor.BLUE]
    assert R.get_factory_tiles(s, 5) == [] and R.get_factory_tiles(s, -1) == []


def test_unknown_center_and_factory_strings_are_ignored():
    s = GameStateData(center_pool=["red", "mystery", "firstPlayer"],
                      players=[PlayerState(index=0, name="a")])
    assert R.get_center_tile_colors(s) == [TileColor.RED]
    s.factories = [[]]
    s.factories[0] = ["blue", "bogus"]            # raw strings, as a lenient parser might leave
    colors = {a.color for a in R.get_legal_actions(s, 0) if a.source_type == SourceType.FACTORY}
    assert colors == {TileColor.BLUE}


# ----------------------------------------------------------------- game engine

def test_new_game_rejects_bad_player_counts():
    with pytest.raises(ValueError):
        G.new_game(["only-one"])
    with pytest.raises(ValueError):
        G.new_game(list("abcde"))


def test_sim_copy_is_independent_and_continues_same_rng():
    a = G.new_game(["A", "B"], seed=4)
    b = a.copy()
    b.state.factories[0].clear()
    assert len(a.state.factories[0]) == 4
    assert a.rng.random() == b.rng.random()


def test_apply_action_rejects_missing_tiles():
    sim = G.new_game(["A", "B"], seed=1)
    missing = next(c for c in TileColor.all_colors() if c not in sim.state.factories[0])
    bad = GameAction(source_type=SourceType.FACTORY, source_index=0, color=missing,
                     destination=DestinationType.FLOOR)
    with pytest.raises(ValueError):
        G.apply_action(sim, bad)
    sim.state.center_pool = [G.FIRST_PLAYER]
    with pytest.raises(ValueError):
        G.apply_action(sim, GameAction(source_type=SourceType.CENTER, color=TileColor.RED,
                                       destination=DestinationType.FLOOR))


def test_floor_overflow_goes_to_lid_and_bag_refills_from_lid():
    sim = G.new_game(["A", "B"], seed=2)
    p = sim.state.players[0]
    p.floor_line = [TileColor.RED] * 7
    sim.state.factories[0] = [TileColor.BLUE] * 4
    G.apply_action(sim, GameAction(source_type=SourceType.FACTORY, source_index=0, color=TileColor.BLUE,
                                   destination=DestinationType.FLOOR))
    assert len(p.floor_line) == 7 and sim.lid.count(TileColor.BLUE) == 4

    sim.bag, sim.lid = [], [TileColor.RED] * 3
    assert G._draw(sim) == TileColor.RED
    assert sim.lid == [] and len(sim.bag) == 2          # lid was reshuffled into the bag
    sim.bag, sim.lid = [], []
    assert G._draw(sim) is None


def test_max_rounds_cutoff_still_returns_scores():
    from tiles.ml.random_player import RandomPlayer
    ps = [RandomPlayer(seed=1), RandomPlayer(seed=2)]
    res = asyncio.run(G.play_game([p.decide for p in ps], ["A", "B"], seed=3, max_rounds=1))
    assert res["rounds"] <= 2 and set(res["scores"]) == {"A", "B"}


def test_play_game_rejects_illegal_decider():
    async def cheat(state, idx):
        return GameAction(source_type=SourceType.FACTORY, source_index=0, color=TileColor.RED,
                          destination=DestinationType.PATTERN_LINE, destination_row=9)

    with pytest.raises(ValueError):
        asyncio.run(G.play_game([cheat, cheat], ["A", "B"], seed=1))


# ----------------------------------------------------------------- archetypes

@pytest.fixture(scope="module")
def corpus():
    games = asyncio.run(ta.simulate(60, seed=9))
    return ta.to_xy(games)


def test_kmeans_model_fit_predict(corpus):
    X, y = corpus
    model = ArchetypeModel.fit(X, 3, seed=0, y=y)
    assert len(model.labels) == 3 and len(set(model.labels)) == 3       # duplicate names disambiguated
    pred = model.predict(X[0])
    assert pred.archetype in model.labels and 0 <= pred.confidence <= 1
    assert model.predict_label(X[0]) in model.labels
    assert pred.standout_features

    unlabeled = ArchetypeModel.fit(X, 2, seed=0)
    assert unlabeled.labels == ["cluster_0", "cluster_1"]


def test_classifier_rejects_mismatched_features(tmp_path, corpus):
    X, y = corpus
    p = tmp_path / "m.json"
    ArchetypeClassifier.fit(X, y).save(p, meta={"k": 1})
    data = json.loads(p.read_text())
    data["feature_names"] = ["other"]
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        ArchetypeClassifier.load(p)


def test_extract_features_ignores_other_players_and_boardless_moves(corpus):
    games = asyncio.run(ta.simulate(2, seed=1))
    moves = games[0]["moves"]
    name = next(iter(games[0]["labels"]))
    assert extract_features([{k: v for k, v in m.items() if k != "board"} for m in moves], name) is None
    f = extract_features(moves, name)
    assert f is not None and f.shape == (len(FEATURE_NAMES),)


# ----------------------------------------------------------------- analyzers

def move(name, color="red", src="factory", dest="pattern_line", row=0, **extra):
    m = {"player_name": name, "action": {"source_type": src, "source_index": 0 if src == "factory" else None,
                                         "color": color, "destination": dest, "destination_row": row}}
    m.update(extra)
    return m


def test_basic_analyzer_style_branches():
    a = BasicProfileAnalyzer()
    assert "No moves" in a.analyze("Z", [])["summary"]
    floorish = [move("P", dest="floor", row=None, src="center") for _ in range(6)]
    p = a.analyze("P", floorish)
    assert "aggressive" in p["style"] and "center-focused" in p["style"]
    clean = [move("Q", color=c, row=i % 5) for i, c in enumerate(["red", "blue", "white", "black", "yellow"] * 2)]
    q = a.analyze("Q", clean)
    assert "conservative" in q["style"] and "factory-focused" in q["style"]
    assert a.description and a.name == "BasicProfileAnalyzer"


def test_archetype_analyzer_edge_cases(corpus):
    X, y = corpus
    an = ArchetypeProfileAnalyzer(ArchetypeClassifier.fit(X, y))
    assert "No moves" in an.analyze("Nobody", [])["summary"]
    few = [move("P") for _ in range(3)]
    out = an.analyze("P", few)
    assert out["archetype"] is None and "not enough" in out["summary"]
    assert an.name == "ArchetypeProfileAnalyzer" and an.description
    assert {a["name"] for a in analyzer_registry.list_all()} >= {"BasicProfileAnalyzer"}


def test_registry_survives_a_bad_model_file(monkeypatch, tmp_path):
    from tiles.ml import analyzers, archetypes
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    monkeypatch.setattr(archetypes, "DEFAULT_MODEL_PATH", bad)
    reg = analyzers.AnalyzerRegistry()
    assert reg.get("BasicProfileAnalyzer") is not None and reg.get("ArchetypeProfileAnalyzer") is None


# ----------------------------------------------------------------- adaptive player

def test_adaptive_without_classifier_plays_balanced(monkeypatch):
    monkeypatch.setattr(AP, "_load_classifier", lambda: None)
    p = AP.AdaptivePlayer(best_response={})
    assert p.infer_opponents() == {}
    w, info = p.choose_weights()
    assert info["playing_as"] == "Balanced"


def test_adaptive_skips_opponents_with_too_few_featured_moves(corpus):
    X, y = corpus
    p = AP.AdaptivePlayer(classifier=ArchetypeClassifier.fit(X, y), best_response={})
    p.MIN_OBSERVED_MOVES = 1
    p.history["Opp"] = [move("Opp", board=None)]            # no board snapshot -> no features
    assert p.infer_opponents() == {}


def test_best_response_file_loading(monkeypatch, tmp_path):
    f = tmp_path / "br.json"
    f.write_text(json.dumps({"responses": {"RusherPlayer": {"best": "Blocker"}}}))
    monkeypatch.setattr(AP, "BEST_RESPONSE_PATH", f)
    assert AP._load_best_response() == {"RusherPlayer": "Blocker"}
    monkeypatch.setattr(AP, "BEST_RESPONSE_PATH", tmp_path / "missing.json")
    assert AP._load_best_response() == {}
