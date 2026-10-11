"""MCTS search-budget sweep (A3 extension): strength vs latency curve.

Plain MCTS against the greedy baseline at increasing simulation budgets.
Shows the trade-off the report's "orchestrated under latency
considerations" claim rests on.
"""

from __future__ import annotations

from typing import List

from tiles.experiments.registry import ExperimentSpec, ParamSpec
from tiles.sim.match import MatchConfig
from tiles.sim.study import run_match_with_stats

from ._common import abort_note, line, mean, pct, result, table


def _parse_budgets(text: str) -> List[int]:
    budgets = []
    for part in str(text).split(","):
        part = part.strip()
        if part:
            budgets.append(int(part))
    return budgets


def validate(params: dict) -> None:
    try:
        budgets = _parse_budgets(params["budgets"])
    except ValueError:
        raise ValueError("budgets must be a comma-separated list of integers") from None
    if not budgets or any(b < 1 or b > 5000 for b in budgets):
        raise ValueError("budgets must contain integers between 1 and 5000")


def run(params: dict, ctx) -> dict:
    budgets = _parse_budgets(params["budgets"])
    games = params["games_per_budget"]
    seed = params["seed"]
    total = len(budgets) * games

    rows = []
    game_stats: List[dict] = []
    done = 0
    for bi, budget in enumerate(budgets):
        wins = 0
        played = 0
        margins: List[float] = []
        decide_ms: List[float] = []
        for g in range(games):
            if ctx.stopped():
                break
            seat = g % 2
            players = [{"name": "greedy", "tactician": "greedy", "config": {}}]
            players.insert(
                seat,
                {"name": "mcts", "tactician": "mcts", "config": {"simulations": budget}},
            )
            labels = ["greedy", "greedy"]
            labels[seat] = "mcts"
            match, stats = run_match_with_stats(
                MatchConfig(players=players, profiler=None, explainer=None,
                            seed=seed + bi * 1000 + g),
                labels,
                game_id=len(game_stats),
                setting=f"{budget}_sims",
                keep_records=True,
            )
            game_stats.append(stats)
            won = match.winner == seat
            wins += int(won)
            played += 1
            margins.append(match.scores[seat] - match.scores[1 - seat])
            decide_ms.extend(
                r["timing"]["decide_ms"] for r in match.records
                if r.get("player_name") == "mcts"
            )
            done += 1
            ctx.progress(done, total,
                         f"{budget} sims: game {g + 1}/{games} ({'won' if won else 'lost'})")
        if played:
            rows.append({
                "simulations": budget,
                "games": played,
                "wins": wins,
                "win_rate": round(wins / played, 3),
                "avg_margin": round(mean(margins), 2),
                "avg_decide_ms": round(mean(decide_ms), 1),
            })
        if ctx.stopped():
            break

    metrics = {}
    for r in rows:
        metrics[f"win_rate_{r['simulations']}"] = r["win_rate"]
        metrics[f"avg_decide_ms_{r['simulations']}"] = r["avg_decide_ms"]
    if rows:
        lo, hi = rows[0], rows[-1]
        summary = (
            f"MCTS vs greedy: win rate {pct(lo['win_rate'])} at {lo['simulations']} sims "
            f"({lo['avg_decide_ms']:.0f} ms/move) rising to {pct(hi['win_rate'])} at "
            f"{hi['simulations']} sims ({hi['avg_decide_ms']:.0f} ms/move)."
        )
    else:
        summary = "No games were played."
    labels = [str(r["simulations"]) for r in rows]
    return result(
        summary=abort_note(ctx) + summary,
        metrics=metrics,
        tables=[
            table("Budget sweep (MCTS vs greedy)",
                  ["simulations", "games", "wins", "win_rate", "avg_margin", "avg_decide_ms"],
                  [[r["simulations"], r["games"], r["wins"], r["win_rate"],
                    r["avg_margin"], r["avg_decide_ms"]] for r in rows]),
        ],
        series=[
            line("Win rate vs simulations", labels,
                 {"win rate": [r["win_rate"] for r in rows]},
                 x_label="simulations per move", y_label="win rate"),
            line("Decision latency vs simulations", labels,
                 {"avg decide ms": [r["avg_decide_ms"] for r in rows]},
                 x_label="simulations per move", y_label="ms"),
        ],
        raw={"rows": rows, "game_stats": game_stats, "params": dict(params)},
    )


SPEC = ExperimentSpec(
    name="search_budget_sweep",
    title="MCTS search-budget sweep",
    description=(
        "Strength-vs-latency curve: plain MCTS against the greedy "
        "baseline at increasing simulation budgets."
    ),
    report_section="5. Strategic search (A3 sims-vs-strength curve)",
    estimated="~1 min at defaults",
    params=(
        ParamSpec("budgets", "str", "25,50,100,200", "Comma-separated simulation budgets"),
        ParamSpec("games_per_budget", "int", 4, "Games per budget (seats alternate)", 1, 100),
        ParamSpec("seed", "int", 0, "Base random seed", 0, 1_000_000),
    ),
    run=run,
    validate=validate,
)
