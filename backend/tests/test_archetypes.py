"""Tests for archetype features, classifier, and the profiler integration."""

import asyncio
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from tiles.ml.analyzers import analyzer_registry
from tiles.ml.archetypes import (
    DEFAULT_MODEL_PATH, FEATURE_NAMES, ArchetypeClassifier, extract_features,
)
import train_archetypes as ta


@pytest.fixture(scope="module")
def games():
    return asyncio.run(ta.simulate(40, seed=3))


def test_features_have_expected_shape_and_range(games):
    g = games[0]
    name = next(iter(g["labels"]))
    f = extract_features(g["moves"], name)
    assert f.shape == (len(FEATURE_NAMES),)
    assert np.all(f >= 0) and np.all(f <= 1.0001)


def test_too_few_moves_returns_none():
    assert extract_features([], "nobody") is None


def test_classifier_beats_chance_on_fresh_games():
    train = asyncio.run(ta.simulate(300, seed=11))
    test = asyncio.run(ta.simulate(80, seed=12))
    Xtr, ytr = ta.to_xy(train)
    Xte, yte = ta.to_xy(test)
    clf = ArchetypeClassifier.fit(Xtr, ytr)
    acc = np.mean([clf.predict_label(x) == t for x, t in zip(Xte, yte)])
    assert acc > 0.35  # chance is 0.20


def test_classifier_roundtrip(tmp_path, games):
    X, y = ta.to_xy(games)
    clf = ArchetypeClassifier.fit(X, y)
    clf.save(tmp_path / "m.json")
    again = ArchetypeClassifier.load(tmp_path / "m.json")
    assert [clf.predict_label(x) for x in X[:20]] == [again.predict_label(x) for x in X[:20]]


@pytest.mark.skipif(not DEFAULT_MODEL_PATH.exists(), reason="run scripts/train_archetypes.py first")
def test_analyzer_adds_archetype_and_reasons(games):
    g = games[0]
    name = next(iter(g["labels"]))
    profile = analyzer_registry.get("ArchetypeProfileAnalyzer").analyze(name, g["moves"])
    assert profile["archetype"] in ArchetypeClassifier.load(DEFAULT_MODEL_PATH).classes
    assert 0 <= profile["archetype_confidence"] <= 1
    assert abs(sum(profile["archetype_scores"].values()) - 1) < 0.01
    assert "Archetype:" in profile["summary"]
