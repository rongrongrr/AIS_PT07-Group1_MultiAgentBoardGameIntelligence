"""Train and evaluate the sequence-model profilers (Transformer, GRU) against the feature baseline.

    python scripts/train_sequence_profiler.py --games 1500 --seed 7

Self-play between the five style-weighted bots gives labelled move sequences. Reports held-out
accuracy per model, also when only the first 5 / 10 / 15 moves have been seen, and saves the best
model to models/sequence_profiler.pt. The feature-based logistic regression (whole-game aggregates)
is evaluated on the same split as the baseline.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import train_archetypes as ta  # noqa: E402
from tiles.ml.archetypes import ArchetypeClassifier, extract_features  # noqa: E402
from tiles.ml.sequence_profiler import DEFAULT_SEQ_MODEL_PATH, SequenceProfiler, sequence_matrix  # noqa: E402


def to_sequences(games):
    seqs, labels, feats = [], [], []
    for g in games:
        for name, label in g["labels"].items():
            s = sequence_matrix(g["moves"], name)
            f = extract_features(g["moves"], name)
            if s is not None and f is not None and len(s) >= 5:
                seqs.append(s)
                labels.append(label)
                feats.append(f)
    return seqs, labels, np.array(feats)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=1500)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--no-save", action="store_true")
    a = ap.parse_args()

    t0 = time.time()
    games = asyncio.run(ta.simulate(a.games, a.seed))
    cut1, cut2 = int(len(games) * 0.7), int(len(games) * 0.85)
    tr, va, te = games[:cut1], games[cut1:cut2], games[cut2:]
    Str, ytr, Ftr = to_sequences(tr)
    Sva, yva, _ = to_sequences(va)
    Ste, yte, Fte = to_sequences(te)
    print(f"sequences  train {len(Str)}  val {len(Sva)}  test {len(Ste)}   (simulated in {time.time() - t0:.0f}s)")

    lr = ArchetypeClassifier.fit(Ftr, ytr)
    lr_acc = float(np.mean([lr.predict_label(x) == t for x, t in zip(Fte, yte)]))

    rows = {"feature LR (whole game)": {"full": lr_acc}}
    best, best_acc = None, -1.0
    for kind in ("transformer", "gru"):
        t = time.time()
        m = SequenceProfiler(kind, seed=a.seed)
        m.fit(Str, ytr, val=(Sva, yva), epochs=a.epochs)
        res = {"full": m.accuracy(Ste, yte)}
        for k in (5, 10, 15):
            res[k] = m.accuracy(Ste, yte, prefix=k)
        rows[kind] = res
        print(f"  trained {kind} in {time.time() - t:.0f}s", flush=True)
        if res["full"] > best_acc:
            best, best_acc = m, res["full"]

    print(f"\n{'model':<26}{'first 5':>9}{'first 10':>10}{'first 15':>10}{'full game':>11}")
    for name, r in rows.items():
        cells = [f"{r[k]:.3f}" if k in r else "    -" for k in (5, 10, 15)]
        print(f"{name:<26}{cells[0]:>9}{cells[1]:>10}{cells[2]:>10}{r['full']:>11.3f}")
    print(f"(chance 0.200; held-out player-games: {len(yte)})")

    if not a.no_save and best is not None:
        best.save(DEFAULT_SEQ_MODEL_PATH, meta={"games": a.games, "seed": a.seed, "held_out_accuracy": round(best_acc, 3),
                                                 "feature_lr_accuracy": round(lr_acc, 3), "kind": best.kind})
        print(f"saved {best.kind} -> {DEFAULT_SEQ_MODEL_PATH}")


if __name__ == "__main__":
    main()
