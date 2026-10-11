"""Turn experiment result files into per-game CSVs and report tables.

    python scripts/study_report.py ../docs/results

Reads every ``*.json`` file written by ``tiles experiment run ... --output``.
Each result table is written as a gzip CSV next to the file. Files that hold
per-game statistics (the heuristic and scaling studies, and the ablation,
tournament and search-budget experiments) also get one CSV row per player per
game. It prints the markdown tables used in
docs/FINAL_REPORT.md (section 10.8). For the heuristic runs the comparison is *paired*: all
variants share the same deals and focal seats, so the score difference
against the baseline on the same game is much less noisy than comparing
two averages.
"""

from __future__ import annotations

import csv
import gzip
import json
import math
import re
import statistics
import sys
from pathlib import Path

PLAYER_COLS = [
    "seat", "label", "tactician", "score", "rank", "won", "shared", "tiling_points",
    "tiles_placed", "floor_penalty", "bonus_rows", "bonus_cols", "bonus_colors",
    "bonus_points", "moves", "floor_move_share", "center_move_share", "fpt_pickups",
    "avg_decide_ms",
]
GAME_COLS = ["game", "setting", "num_players", "seed", "steps", "rounds", "duration_s", "winner_seat", "focal_seat"]


def load(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf8"))
    return data.get("result", data)


def games_of(result: dict) -> list:
    """The per-game statistics in a result, or an empty list if it has none."""
    raw = result.get("raw") or {}
    for key in ("game_stats", "games"):
        rows = raw.get(key) or []
        if (
            isinstance(rows, list)
            and rows
            and isinstance(rows[0], dict)
            and isinstance(rows[0].get("players"), list)
            and rows[0]["players"]
            and isinstance(rows[0]["players"][0], dict)
        ):
            return rows
    return []


def write_tables(path: Path, result: dict) -> list:
    """Write each table of a result as ``<file>__<table title>.csv.gz``."""
    written = []
    for table in result.get("tables") or []:
        slug = re.sub(r"[^a-z0-9]+", "_", table["title"].lower()).strip("_")[:50]
        out = path.with_name(f"{path.stem}__{slug}.csv.gz")
        with gzip.open(out, "wt", newline="", encoding="utf8") as fh:
            w = csv.writer(fh)
            w.writerow(table["columns"])
            w.writerows(table["rows"])
        written.append(out.name)
    return written


def write_csv(path: Path, games: list) -> None:
    with gzip.open(path, "wt", newline="", encoding="utf8") as fh:
        w = csv.writer(fh)
        w.writerow(GAME_COLS + PLAYER_COLS)
        for g in games:
            head = [g.get(c) for c in GAME_COLS]
            for p in g["players"]:
                w.writerow(head + [p[c] for c in PLAYER_COLS])


def paired(games: list, variant: str, baseline: str = "baseline") -> dict:
    """Paired score / win differences of ``variant`` against ``baseline``."""
    base = {g["game"] % 10**9: g for g in games if g["setting"] == baseline}
    by_index = {}
    for g in games:
        by_index.setdefault(g["setting"], []).append(g)
    base_games = by_index[baseline]
    var_games = by_index[variant]
    ds, dw = [], []
    for b, v in zip(base_games, var_games):
        fb = next(p for p in b["players"] if p["label"] == "focal")
        fv = next(p for p in v["players"] if p["label"] == "focal")
        ds.append(fv["score"] - fb["score"])
        dw.append((fv["won"] + 0.5 * fv["shared"]) - (fb["won"] + 0.5 * fb["shared"]))
    del base

    def ci(xs):
        m = statistics.fmean(xs)
        return m, 1.96 * statistics.stdev(xs) / math.sqrt(len(xs))

    sm, sc = ci(ds)
    wm, wc = ci(dw)
    return {"score_diff": sm, "score_ci": sc, "win_diff": wm, "win_ci": wc, "n": len(ds)}


def main(folder: str) -> None:
    root = Path(folder)
    for path in sorted(root.glob("*.json")):
        result = load(path)
        tables = write_tables(path, result)
        if tables:
            print(f"\n### {path.name}: tables -> {', '.join(tables)}")
        games = games_of(result)
        if not games:
            continue
        write_csv(path.with_suffix(".csv.gz"), games)
        print(f"\n### {path.name}: {len(games)} games -> {path.with_suffix('.csv.gz').name}")
        if path.name.startswith("heuristics_"):
            variants = list(dict.fromkeys(g["setting"] for g in games))
            print("| variant | win rate | paired win diff | paired score diff | floor pen. | bonus pts | FPT/game |")
            print("|---|---|---|---|---|---|---|")
            rows = {r[0]: r for r in result["tables"][0]["rows"]}
            for v in variants:
                r = rows[v]
                if v == "baseline":
                    print(f"| {v} | {r[1]:.1%} | - | - | {r[6]:.1f} | {r[7]:.1f} | {r[10]:.2f} |")
                    continue
                d = paired(games, v)
                print(
                    f"| {v} | {r[1]:.1%} | {d['win_diff']:+.1%} ± {d['win_ci']:.1%} | "
                    f"{d['score_diff']:+.1f} ± {d['score_ci']:.1f} | {r[6]:.1f} | {r[7]:.1f} | {r[10]:.2f} |"
                )
        else:
            for t in result["tables"]:
                print(f"\n{t['title']}\n")
                print("| " + " | ".join(t["columns"]) + " |")
                print("|" + "---|" * len(t["columns"]))
                for row in t["rows"]:
                    print("| " + " | ".join(str(c) for c in row) + " |")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../docs/results")
