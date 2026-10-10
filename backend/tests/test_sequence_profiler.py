"""Sequence-model profiler (Transformer / GRU) and its analyzer."""

import asyncio
import sys
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import train_archetypes as ta  # noqa: E402
from tiles.ml import sequence_profiler as sp  # noqa: E402
from tiles.ml.analyzers import SequenceProfileAnalyzer  # noqa: E402


@pytest.fixture(scope="module")
def corpus():
    games = asyncio.run(ta.simulate(60, seed=11))
    seqs, labels, names = [], [], []
    for g in games:
        for name, label in g["labels"].items():
            s = sp.sequence_matrix(g["moves"], name)
            if s is not None and len(s) >= 5:
                seqs.append(s)
                labels.append(label)
                names.append((g, name))
    return seqs, labels, names


def test_move_features_shape_range_and_known_values(corpus):
    seqs, _, _ = corpus
    s = seqs[0]
    assert s.shape[1] == sp.D_IN == len(sp.MOVE_FEATURES)
    assert s.min() >= 0 and s.max() <= 1.0001
    assert np.allclose(s[:, :5].sum(1), 1)                     # exactly one colour per move
    assert np.allclose(s[:, 6:12].sum(1), 1)                   # exactly one destination
    assert sp.sequence_matrix([], "nobody") is None


@pytest.mark.parametrize("kind", ["transformer", "gru"])
def test_models_learn_and_roundtrip(kind, corpus, tmp_path):
    seqs, labels, names = corpus
    m = sp.SequenceProfiler(kind, seed=1)
    hist = m.fit(seqs, labels, val=(seqs[:20], labels[:20]), epochs=12, batch=32)
    assert hist["loss"][-1] < hist["loss"][0]
    acc = m.accuracy(seqs, labels)
    assert acc > 0.45                                           # chance is 0.20 (train accuracy, small model)
    assert m.accuracy(seqs, labels, prefix=5) > 0.3
    path = tmp_path / "m.pt"
    m.save(path, meta={"k": 1})
    again = sp.SequenceProfiler.load(path)
    assert [m.predict_label(s) for s in seqs[:15]] == [again.predict_label(s) for s in seqs[:15]]

    g, name = names[0]
    pred = again.predict(g["moves"], name)
    assert pred.archetype in again.classes and abs(sum(pred.scores.values()) - 1) < 0.01
    assert len(pred.standout_features) == 3 and pred.standout_features[0]["importance"] >= pred.standout_features[-1]["importance"]
    assert again.predict([], "nobody") is None


def test_load_rejects_mismatched_features(tmp_path, corpus):
    seqs, labels, _ = corpus
    m = sp.SequenceProfiler("gru", seed=1)
    m.fit(seqs[:30], labels[:30], epochs=1)
    path = tmp_path / "m.pt"
    m.save(path)
    blob = torch.load(path, weights_only=False)
    blob["features"] = ["other"]
    torch.save(blob, path)
    with pytest.raises(ValueError):
        sp.SequenceProfiler.load(path)
    with pytest.raises(ValueError):
        sp.build_net("rnn-unknown", 5)


def test_analyzer_adds_archetype_reasons_and_handles_edge_cases(corpus):
    seqs, labels, names = corpus
    m = sp.SequenceProfiler("transformer", seed=1)
    m.fit(seqs[:80], labels[:80], epochs=3, batch=32)
    an = SequenceProfileAnalyzer(m)
    g, name = names[0]
    out = an.analyze(name, g["moves"])
    assert out["archetype"] in m.classes and out["model_kind"] == "transformer"
    assert "sequence model" in an.description and an.name == "SequenceProfileAnalyzer"
    assert "Archetype (transformer)" in out["summary"] and out["archetype_reasons"]
    assert "No moves" in an.analyze("nobody", g["moves"])["summary"]
    boardless = [{k: v for k, v in mv.items() if k != "board"} for mv in g["moves"]]
    assert an.analyze(name, boardless)["archetype"] is None
