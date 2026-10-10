"""Rule-extraction benchmark and rulebook ingestion demo.

    python scripts/rule_extraction_benchmark.py --count 100 --seed 1
    python scripts/rule_extraction_benchmark.py --rulebook ../docs/rules/azul_rules.md

Prints per-field accuracy on generated rulebooks (randomised parameter values + distractors)
for the dev / held-out / fresh phrasing groups, then ingests the real corpus and checks the
extracted rules against the engine.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rules_ingest.benchmark import run_benchmark  # noqa: E402
from app.rules_ingest.extract import PatternExtractor  # noqa: E402
from app.rules_ingest.ingest import ingest_file  # noqa: E402
from app.rules_ingest.schema import FIELDS  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=100, help="generated rulebooks per group")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--rulebook", default=str(Path(__file__).resolve().parents[2] / "docs" / "rules" / "azul_rules.md"))
    ap.add_argument("--out", help="write the full results as JSON")
    a = ap.parse_args()

    ex = PatternExtractor()
    results = {}
    print(f"{'field':<26}" + "".join(f"{g:>10}" for g in ("dev", "heldout", "fresh")))
    for g in ("dev", "heldout", "fresh"):
        results[g] = run_benchmark(ex, g, a.count, a.seed)
    for f in FIELDS:
        print(f"{f:<26}" + "".join(f"{results[g]['per_field'][f]:>10.2f}" for g in results))
    print(f"{'FIELD ACCURACY':<26}" + "".join(f"{results[g]['field_accuracy']:>10.3f}" for g in results))
    print(f"{'WHOLE RULEBOOK EXACT':<26}" + "".join(f"{results[g]['rulebook_exact']:>10.2f}" for g in results))

    res = ingest_file(a.rulebook, ex)
    print(f"\nReal corpus ({Path(a.rulebook).name}): {sum(res.field_matches.values())}/{len(FIELDS)} fields match the engine; "
          f"wall layout rebuilds the standard wall: {res.wall_matches_standard}; config built: {res.config is not None}")
    if a.out:
        for g in results:
            results[g].pop("failures", None)
        Path(a.out).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
