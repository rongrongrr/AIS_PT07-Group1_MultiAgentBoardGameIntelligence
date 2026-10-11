"""Profiler ablation — the report's headline experiment (A1).

Same MCTS Tactician with and without the Profiler's predicted opponent
policy injected into the search, against a fixed denial-heavy opponent,
plus the greedy baseline. Isolates the win-rate contribution of
opponent modeling.
"""

from __future__ import annotations

from tiles.experiments.registry import ExperimentSpec, ParamSpec
from tiles.sim.ablation import run_ablation

from ._common import abort_note, bar, pct, result, table


def run(params: dict, ctx) -> dict:
    conditions = run_ablation(
        games=params["games"],
        simulations=params["simulations"],
        seed=params["seed"],
        tracker_backend=params["tracker"],
        on_progress=ctx.progress,
        stop_check=ctx.stopped,
        verbose=False,
    )
    rows = [c.to_dict() for c in conditions]
    by_name = {r["condition"]: r for r in rows}
    labels = [r["condition"] for r in rows]

    metrics = {}
    for r in rows:
        metrics[f"win_rate_{r['condition']}"] = r["win_rate"]
        metrics[f"avg_margin_{r['condition']}"] = r["avg_margin"]
        metrics[f"avg_decision_ms_{r['condition']}"] = r["avg_decision_ms"]

    profiled = by_name.get("mcts_profiled")
    plain = by_name.get("mcts")
    greedy = by_name.get("greedy")
    if profiled and plain and plain["games"] and profiled["games"]:
        uplift = profiled["win_rate"] - plain["win_rate"]
        metrics["profiler_uplift"] = uplift
        summary = (
            f"mcts_profiled won {pct(profiled['win_rate'])} of {profiled['games']} games "
            f"vs {pct(plain['win_rate'])} for plain mcts "
            f"({uplift:+.0%} uplift; avg margin {profiled['avg_margin']:+.1f} vs "
            f"{plain['avg_margin']:+.1f} pts)"
        )
        if greedy:
            summary += f"; greedy baseline {pct(greedy['win_rate'])}"
        summary += (
            f". Profiling cost {profiled['avg_decision_ms'] - plain['avg_decision_ms']:+.0f} ms "
            f"per decision."
        )
    else:
        summary = "Not enough completed conditions to compare mcts_profiled with mcts."
    summary = abort_note(ctx) + summary

    return result(
        summary=summary,
        metrics=metrics,
        tables=[
            table(
                "Conditions (subject vs fixed blocker)",
                ["condition", "games", "wins", "win_rate", "avg_margin", "avg_decision_ms"],
                [
                    [r["condition"], r["games"], r["wins"], r["win_rate"],
                     r["avg_margin"], r["avg_decision_ms"]]
                    for r in rows
                ],
            )
        ],
        series=[
            bar("Win rate by condition", labels,
                {"win rate": [r["win_rate"] for r in rows]},
                x_label="condition", y_label="win rate"),
            bar("Average score margin", labels,
                {"avg margin (pts)": [r["avg_margin"] for r in rows]},
                x_label="condition", y_label="points"),
            bar("Decision latency", labels,
                {"avg decide ms": [r["avg_decision_ms"] for r in rows]},
                x_label="condition", y_label="ms"),
        ],
        raw={
            "conditions": rows,
            "game_stats": [g for c in conditions for g in c.game_stats],
            "params": dict(params),
        },
    )


SPEC = ExperimentSpec(
    name="profiler_ablation",
    title="Profiler ablation",
    description=(
        "Does opponent modeling help? Plays greedy, plain MCTS, and "
        "profiler-conditioned MCTS against a fixed denial-heavy blocker "
        "and compares win rate, score margin, and decision latency."
    ),
    report_section="7. Evaluation (A1 headline result)",
    estimated="~1-2 min at defaults",
    params=(
        ParamSpec("games", "int", 6, "Games per condition (seats alternate)", 1, 200),
        ParamSpec("simulations", "int", 100, "MCTS simulations per move", 10, 2000),
        ParamSpec("seed", "int", 0, "Base random seed", 0, 1_000_000),
        ParamSpec("tracker", "str", "null", "Experiment tracker backend",
                  choices=("null", "jsonl", "mlflow", "auto")),
    ),
    run=run,
)
