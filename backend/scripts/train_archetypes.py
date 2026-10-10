"""Generate self-play games between style archetypes, fit the archetype clusterer,
and report held-out accuracy.

    python scripts/train_archetypes.py --games 400 --seed 7
    python scripts/train_archetypes.py --games 400 --seed 7 --no-save

Ground-truth labels (which archetype generated each player-game) are used only
to name clusters and to score the result; the clustering itself is unsupervised.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.azul.game import play_game  # noqa: E402
from app.ml.archetypes import (  # noqa: E402
    DEFAULT_MODEL_PATH, FEATURE_NAMES, ArchetypeClassifier, ArchetypeModel, extract_features, move_record,
)  # noqa: E402
from app.ml.greedy_player import (  # noqa: E402
    BlockerPlayer, ColorCollectorPlayer, GreedyPlayer, RecklessPlayer, RusherPlayer,
)

CLASSES = [GreedyPlayer, ColorCollectorPlayer, RusherPlayer, RecklessPlayer, BlockerPlayer]


def snapshot(sim, idx, action) -> dict:
    return move_record(sim.state, idx, action)


async def simulate(n_games: int, seed: int):
    rng = random.Random(seed)
    games = []
    for g in range(n_games):
        a, b = rng.choice(CLASSES), rng.choice(CLASSES)
        names = [f"p0_{a.__name__}", f"p1_{b.__name__}"]
        log = []
        await play_game([a().decide, b().decide], names, seed=rng.randrange(10**9),
                        on_move=lambda sim, i, act: log.append(snapshot(sim, i, act)))
        games.append({"labels": {names[0]: a.__name__, names[1]: b.__name__}, "moves": log})
    return games


def to_xy(games):
    X, y = [], []
    for g in games:
        for name, label in g["labels"].items():
            f = extract_features(g["moves"], name)
            if f is not None:
                X.append(f)
                y.append(label)
    return np.array(X), y


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--k", type=int, default=len(CLASSES))
    ap.add_argument("--no-save", action="store_true")
    args = ap.parse_args()

    games = asyncio.run(simulate(args.games, args.seed))
    cut = int(len(games) * 0.7)
    Xtr, ytr = to_xy(games[:cut])
    Xte, yte = to_xy(games[cut:])

    from sklearn.metrics import adjusted_rand_score

    base = Counter(yte).most_common(1)[0][1] / len(yte)
    print(f"train player-games: {len(ytr)}  held-out: {len(yte)}  "
          f"(majority-class baseline {base:.1%}, chance {1/len(CLASSES):.1%})")

    # 1) Unsupervised discovery: do the styles form natural clusters?
    km = ArchetypeModel.fit(Xtr, args.k, seed=args.seed, y=ytr)
    km_pred = [km.predict_label(x) for x in Xte]
    print(f"\n[k-means, k={args.k}] held-out ARI vs true style: {adjusted_rand_score(yte, km_pred):.3f} "
          f"(0 = random). Styles overlap too much per game to separate without labels.")

    # 2) Supervised identification (used by the profiler)
    clf = ArchetypeClassifier.fit(Xtr, ytr)
    pred = [clf.predict_label(x) for x in Xte]
    acc = float(np.mean([p == t for p, t in zip(pred, yte)]))
    print(f"\n[logistic regression] held-out accuracy: {acc:.1%}")
    cols = sorted(set(yte))
    print("confusion (rows = true, cols = predicted):")
    print(" " * 22 + " ".join(f"{c[:10]:>10}" for c in cols))
    for t in cols:
        print(f"{t:<22}" + " ".join(f"{sum(1 for p, tt in zip(pred, yte) if tt == t and p == c):>10}" for c in cols))

    if not args.no_save:
        clf_all = ArchetypeClassifier.fit(np.vstack([Xtr, Xte]), list(ytr) + list(yte))
        clf_all.save(DEFAULT_MODEL_PATH, meta={
            "games": args.games, "seed": args.seed, "held_out_accuracy": round(acc, 3),
            "kmeans_adjusted_rand_index": round(adjusted_rand_score(yte, km_pred), 3),
            "chance": round(1 / len(CLASSES), 3), "trained_on": "simulated self-play",
        })
        print(f"saved -> {DEFAULT_MODEL_PATH}")


if __name__ == "__main__":
    main()
