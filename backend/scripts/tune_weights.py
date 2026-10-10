"""Tune GreedyPlayer's heuristic weights with a genetic algorithm, then validate on unseen deals.

    python scripts/tune_weights.py --generations 8 --population 16 --seed 5

Fitness is the margin against a reference pool (balanced Greedy, Blocker, Rusher). The best genome
is saved to models/ga_weights.json and re-evaluated against the default weights and against the
pool on deals the GA never saw.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from duel import duel  # noqa: E402

from tiles.ml.greedy_player import BlockerPlayer, DEFAULT_WEIGHTS, GreedyPlayer, RusherPlayer  # noqa: E402
from tiles.ml.tuning import GENES, evolve, to_genome  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "models" / "ga_weights.json"


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--generations", type=int, default=8)
    ap.add_argument("--population", type=int, default=16)
    ap.add_argument("--deals", type=int, default=4, help="deals per fitness evaluation")
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--validate", type=int, default=60, help="unseen deals for validation")
    ap.add_argument("--mlflow", action="store_true")
    a = ap.parse_args()

    pool = [GreedyPlayer, BlockerPlayer, RusherPlayer]
    res = await evolve(pool, a.population, a.generations, a.deals, a.seed,
                       on_generation=lambda g, b, m: print(f"  gen {g}: best {b:6.1f}  mean {m:6.1f}", flush=True))
    w = res.best
    print("\n{:<10}{:>10}{:>10}".format("gene", "default", "tuned"))
    for g, d, t in zip(GENES, to_genome(DEFAULT_WEIGHTS), to_genome(w)):
        print(f"{g:<10}{d:>10.2f}{t:>10.2f}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"weights": dict(zip(GENES, to_genome(w))), "fitness": res.best_fitness,
                               "seed": a.seed, "generations": a.generations, "history": res.history}, indent=2))

    val_seed = a.seed + 1000          # deals the GA never saw
    tuned = lambda: GreedyPlayer(weights=w)  # noqa: E731
    r = await duel(tuned, GreedyPlayer, a.validate, val_seed)
    print(f"\nvalidation on unseen deals ({r['games']} games): tuned vs default Greedy win {r['win_rate']:.2f} "
          f"{r['ci95']} margin {r['mean_score_diff']:+.1f}")
    metrics = {"fitness": res.best_fitness, "validation_win_rate": r["win_rate"], "validation_margin": r["mean_score_diff"]}
    for opp in (BlockerPlayer, RusherPlayer):
        rr = await duel(tuned, opp, a.validate // 2, val_seed)
        print(f"  tuned vs {opp.__name__}: win {rr['win_rate']:.2f} {rr['ci95']} margin {rr['mean_score_diff']:+.1f}")
        metrics[f"validation_win_rate.{opp.__name__}"] = rr["win_rate"]
    if a.mlflow:
        from tiles import tracking
        tracking.log_run(tracking.EVALUATION_EXPERIMENT, "ga weight tuning",
                         params={**{f"w.{g}": round(v, 3) for g, v in zip(GENES, to_genome(w))},
                                 "generations": a.generations, "population": a.population, "seed": a.seed},
                         metrics=metrics, tags={"kind": "ga"}, series={"best_fitness": [h["best"] for h in res.history],
                                                                         "mean_fitness": [h["mean"] for h in res.history]})


if __name__ == "__main__":
    asyncio.run(main())
