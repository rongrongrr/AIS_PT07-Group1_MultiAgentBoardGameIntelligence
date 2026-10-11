"""Recompute the report's derived figures from the CSV files alone.

    python scripts/recompute_from_csv.py <folder holding the 10.x subfolders>

Prints the figures of Section 10.1 (including the odd-opponent test), 10.3, 10.4, 10.8 and 10.9 of docs/FINAL_REPORT.md
that are not stored in a table file, so that anyone with the CSVs can check
them. Sections 10.2, 10.5, 10.6 and 10.7, and the other tables of 10.1 and
10.4, are read straight from the table files and need no calculation.

Method
------
* Per-game files have one row per player per game. ``label`` marks the player
  under test ("focal") and its opponents.
* Win share = wins + 0.5 x shared wins, divided by games.
* Paired difference of a version against the baseline: the version's value minus
  the baseline's value in the same game position (the nth game of each setting
  was dealt from the same seed and seat), averaged over games, with a margin of
  error of 1.96 x standard deviation / sqrt(games).
* Win-rate intervals are Wilson 95 % intervals.
"""

from __future__ import annotations

import collections
import csv
import gzip
import math
import statistics
import sys
from pathlib import Path


def rows(path: Path) -> list:
    with gzip.open(path, "rt", encoding="utf8") as fh:
        return list(csv.DictReader(fh))


def games(path: Path) -> dict:
    """setting -> list of games, each a list of player rows."""
    by = collections.OrderedDict()
    for r in rows(path):
        by.setdefault((r["setting"], int(r["game"])), []).append(r)
    out = collections.defaultdict(list)
    for (setting, _), g in by.items():
        out[setting].append(g)
    return out


def player(game: list, label: str = "focal") -> dict:
    return next(p for p in game if p["label"] == label)


def win_share(game_list: list, label: str = "focal") -> float:
    return sum(float(player(g, label)["won"]) + 0.5 * float(player(g, label)["shared"]) for g in game_list) / len(game_list)


def margin(xs: list) -> tuple:
    return statistics.fmean(xs), 1.96 * statistics.stdev(xs) / math.sqrt(len(xs))


def paired(by: dict, version: str, base: str = "baseline") -> tuple:
    score, win = [], []
    for b, v in zip(by[base], by[version]):
        pb, pv = player(b), player(v)
        score.append(float(pv["score"]) - float(pb["score"]))
        win.append(float(pv["won"]) + 0.5 * float(pv["shared"]) - float(pb["won"]) - 0.5 * float(pb["shared"]))
    return margin(score), margin(win)


def wilson(successes: float, n: int) -> tuple:
    z = 1.96
    p = successes / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def pm(v: tuple, scale: float = 1.0, digits: int = 1) -> str:
    return f"{v[0] * scale:+.{digits}f} ± {v[1] * scale:.{digits}f}"


def main(root: str) -> None:
    root = Path(root)

    print("## 10.3 Playing styles (from the confusion and cluster tables)")
    for seed in (11, 12):
        d = root / "10.3_playing_styles"
        conf = rows(next(d.glob(f"archetype_seed{seed}__preset_x*.csv.gz")))
        clus = rows(d / f"archetype_seed{seed}__clusters.csv.gz")
        diag = sum(int(r[r["expected"]]) for r in conf)
        total = sum(int(r[c]) for r in conf for c in r if c not in ("preset", "expected"))
        purity = sum(int(r["size"]) * float(r["purity"]) for r in clus) / sum(int(r["size"]) for r in clus)
        print(f"seed {seed}: label matches intended style {diag}/{total} = {diag / total:.0%}; k-means purity {purity:.0%}")
        if seed == 12:
            groups = [("blocker", "risk_taker", ["aggressive_blocker", "risk_taker"]),
                      ("cautious", None, ["cautious_optimizer"]),
                      ("collector", "vanilla", ["set_collector", "greedy_scorer"])]
            hit = 0
            for first, second, labels in groups:
                for r in conf:
                    if r["preset"] in (first, second):
                        hit += sum(int(r[l]) for l in labels)
            print(f"seed 12: right one of three groups {hit}/{total} = {hit / total:.0%}")

    print("\n## 10.1 Profiler ablation at 50 playouts, 200 games per bot")
    d = root / "10.1_profiler_ablation"
    for r in rows(d / "ablation_50_playouts_200_games__conditions_subject_vs_fixed_blocker.csv.gz"):
        n, w = int(r["games"]), int(r["wins"])
        lo, hi = wilson(w, n)
        margins = [float(player(g, "subject")["score"]) - float(player(g, "blocker")["score"])
                   for g in games(d / "ablation_50_playouts_200_games.csv.gz")[r["condition"]]]
        print(f"{r['condition']}: {w}/{n} = {w / n:.1%} [{lo:.0%}-{hi:.0%}], margin {pm(margin(margins))}")

    print("\n## 10.1 and 10.4 mcts against mcts_profiled")
    t = root / "10.4_tactician_strength"
    sets = {"tournament, 30 games": [r for r in rows(t / "tournament_30_games_per_pair__games.csv.gz")
                                     if {r["first"], r["second"]} == {"mcts", "mcts_profiled"}],
            "head-to-head, 200 games": rows(d / "head_to_head_mcts_vs_mcts_profiled_200_games__games.csv.gz")}
    total = [0, 0, 0]
    diffs = []
    for name, rs in sets.items():
        c = [0, 0, 0]
        for r in rs:
            k = 2 if r["winner"] == "tie" else (0 if r["winner"] == "mcts" else 1)
            c[k] += 1
            total[k] += 1
            sa, sb = (int(x) for x in r["score"].split("-"))
            diffs.append((sb - sa) if r["first"] == "mcts" else (sa - sb))
        print(f"{name}: mcts {c[0]}, mcts_profiled {c[1]}, level {c[2]}")
    decided = total[0] + total[1]
    lo, hi = wilson(total[1], decided)
    print(f"pooled {sum(total)} games: mcts {total[0]}, mcts_profiled {total[1]}, level {total[2]}; "
          f"mcts_profiled won {total[1] / decided:.1%} of decided games [{lo:.0%}-{hi:.0%}]; "
          f"its score margin {pm(margin(diffs))}")

    for title, stem in (("the default Profiler", "opponent_styles_25_playouts"),
                        ("the extended Profiler", "opponent_styles_25_playouts_extended_profiler")):
        print(f"\n## 10.1 Opponent model against four odd opponents, {title} (25 playouts, 150 games per bot and style)")
        by = games(d / f"{stem}.csv.gz")
        pooled_w, pooled_m = [], []
        for style in ("colour_loyal", "centre_averse", "low_rows", "noisy"):
            plain, prof = by[f"{style}/mcts"], by[f"{style}/mcts_profiled"]
            dw = [(float(player(q, "subject")["won"]) + 0.5 * float(player(q, "subject")["shared"]))
                  - (float(player(p_, "subject")["won"]) + 0.5 * float(player(p_, "subject")["shared"]))
                  for p_, q in zip(plain, prof)]
            dm = [(float(player(q, "subject")["score"]) - float(player(q, "opponent")["score"]))
                  - (float(player(p_, "subject")["score"]) - float(player(p_, "opponent")["score"]))
                  for p_, q in zip(plain, prof)]
            pooled_w += dw
            pooled_m += dm
            print(f"{style}: mcts {win_share(plain, 'subject'):.1%}, mcts_profiled {win_share(prof, 'subject'):.1%}, "
                  f"win difference {pm(margin(dw), 100)} points, margin difference {pm(margin(dm))}")
        print(f"all four styles: win difference {pm(margin(pooled_w), 100)} points, margin difference {pm(margin(pooled_m))}")
        for r in rows(d / f"{stem}__next_move_prediction_on_these_opponents.csv.gz"):
            print(f"prediction on {r['style']}: Profiler top-1 {float(r['profiler_top1']):.1%}, fixed guesser {float(r['static_top1']):.1%}, "
                  f"top-3 {float(r['profiler_top3']):.1%} against {float(r['static_top3']):.1%}")

    print("\n## 10.4 Head-to-head totals (30 games per pair)")
    tally = collections.defaultdict(lambda: [0, 0, 0])
    for r in rows(t / "tournament_30_games_per_pair__games.csv.gz"):
        a, b = sorted((r["first"], r["second"]))
        tally[(a, b)][2 if r["winner"] == "tie" else (0 if r["winner"] == a else 1)] += 1
    for (a, b), (wa, wb, lv) in sorted(tally.items()):
        print(f"{a} {wa} - {wb} {b} ({lv} level)")

    h = root / "10.8_heuristics"
    print("\n## 10.8 Points gained or lost against the baseline (paired, ± margin of error)")
    for n in (2, 3, 4):
        by = games(h / f"heuristics_{n}p.csv.gz")
        by.update({k: v for k, v in games(h / f"heuristics_extreme_{n}p.csv.gz").items() if k != "baseline"})
        print(f"\n{n} players, 300 games per version (baseline win share {win_share(by['baseline']):.1%})")
        for v in by:
            if v != "baseline":
                s, w = paired(by, v)
                print(f"  {v:20} score {pm(s)}   win share {pm(w, 100)} points")
    for label, f, versions in (("first run of new parts", "heuristics_new_{n}p", ["table_aware", "round_end", "floor_outlook"]),
                               ("second run of new parts", "heuristics_round2_{n}p", ["spoil", "bonus_reach", "endgame", "best_of_all"]),
                               ("follow-up on new deals", "heuristics_followup_{n}p", ["tempo_fpt", "tempo_extreme", "floor_averse"])):
        for n in (2, 3, 4):
            by = games(h / (f.format(n=n) + ".csv.gz"))
            print(f"\n{label}, {n} players, baseline win share {win_share(by['baseline']):.1%}")
            for v in versions:
                s, w = paired(by, v)
                print(f"  {v:16} score {pm(s)}  win diff {pm(w, 100)}  win share {win_share(by[v]):.1%}")
    by = games(h / "heuristics_fpt_3p.csv.gz")
    print("\nfirst-player weight, 3 players, 2,000 games:", "score", pm(paired(by, "table_aware")[0]), "win", pm(paired(by, "table_aware")[1], 100))
    for f in ("heuristics_vs_minimax_2p", "heuristics_vs_minimax_3p", "heuristics_vs_minimax_4p", "heuristics_vs_mcts_2p"):
        by = games(h / f"{f}.csv.gz")
        s, w = paired(by, "best_of_all")
        print(f"{f}: {len(by['baseline'])} games per version, baseline {win_share(by['baseline']):.1%}, all four "
              f"{win_share(by['best_of_all']):.1%}, win diff {pm(w, 100)}, score {pm(s)}")

    p = root / "10.9_player_count"
    print("\n## 10.9 Greedy playing itself (300 games per size)")
    by = games(p / "scaling_greedy.csv.gz")
    for n in (2, 3, 4):
        gs = by[f"self-{n}p"]
        score = statistics.fmean(float(x["score"]) for g in gs for x in g)
        floor = statistics.fmean(float(x["floor_penalty"]) for g in gs for x in g)
        moves = statistics.fmean(int(g[0]["steps"]) for g in gs)
        lead = statistics.fmean(max(float(x["score"]) for x in g) - min(float(x["score"]) for x in g) for g in gs)
        first = sum(g[0]["winner_seat"] == "1" for g in gs) / len(gs)
        last = sum(g[0]["winner_seat"] == str(n) for g in gs) / len(gs)
        print(f"{n} players: score {score:.1f}, floor {floor:.1f}, moves {moves:.0f}, lead {lead:.1f}, first seat {first:.1%}, last seat {last:.1%}")

    print("\n## 10.9 mcts against greedy players (pooled files)")
    a, b = games(p / "mcts_followup.csv.gz"), games(p / "mcts_4p_followup.csv.gz")
    for n in (2, 3, 4):
        gs = a.get(f"field-{n}p", []) + b.get(f"field-{n}p", [])
        wins = sum(float(player(g)["won"]) + 0.5 * float(player(g)["shared"]) for g in gs)
        lo, hi = wilson(wins, len(gs))
        mine = statistics.fmean(float(player(g)["score"]) for g in gs)
        fill = statistics.fmean(float(x["score"]) for g in gs for x in g if x["label"] == "filler")
        ms = statistics.fmean(float(player(g)["avg_decide_ms"]) for g in gs)
        print(f"{n} players: {len(gs)} games, win {wins / len(gs):.1%} [{lo:.0%}-{hi:.0%}], x fair share {wins / len(gs) * n:.2f}, "
              f"score {mine:.1f} vs {fill:.1f}, decision {ms:.0f} ms")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "../docs/results")
