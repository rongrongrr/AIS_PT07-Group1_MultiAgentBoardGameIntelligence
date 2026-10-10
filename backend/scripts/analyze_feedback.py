"""Summarise the human evaluation of explanations (run after collecting ratings in the UI).

    python scripts/analyze_feedback.py

Prints, per rating scale, the number of ratings, mean and 95% CI, overall and per player model.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tiles.models.db import ExplanationFeedback, SessionLocal  # noqa: E402
from tiles.routers.feedback import ITEMS, mean_ci  # noqa: E402


def main():
    db = SessionLocal()
    rows = db.query(ExplanationFeedback).all()
    if not rows:
        print("No ratings yet. Collect them in the Game Monitor or Replay (rate the explanation under a move).")
        return
    print(f"{len(rows)} ratings from {len({r.rater for r in rows})} raters\n")
    groups = {"ALL": rows}
    for r in rows:
        groups.setdefault(r.model or "unknown", []).append(r)
    print(f"{'group':<22}{'n':>5}" + "".join(f"{i:>26}" for i in ITEMS))
    for name, rs in groups.items():
        cells = []
        for i in ITEMS:
            s = mean_ci([getattr(r, i) for r in rs])
            ci = f" [{s['ci95'][0]:.2f}, {s['ci95'][1]:.2f}]" if s["ci95"] else ""
            cells.append(f"{s['mean']:.2f}{ci}")
        print(f"{name:<22}{len(rs):>5}" + "".join(f"{c:>26}" for c in cells))
    comments = [r.comment for r in rows if r.comment]
    if comments:
        print("\nComments:")
        for c in comments[:20]:
            print(" -", c)


if __name__ == "__main__":
    main()
