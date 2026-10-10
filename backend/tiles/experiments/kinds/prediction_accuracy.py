"""Opponent-model prediction accuracy (A2).

Next-move prediction accuracy of the Profiler vs a uniform guess and a
static (non-adaptive) greedy model, split by game phase to show the
prior→posterior transition.
"""

from __future__ import annotations

from tiles.experiments.registry import ExperimentSpec, ParamSpec
from tiles.sim.prediction_eval import PHASES, evaluate_prediction_accuracy

from ._common import abort_note, bar, line, pct, result, table

MODELS = ("predictor", "static_greedy", "uniform")


def run(params: dict, ctx) -> dict:
    report = evaluate_prediction_accuracy(
        games=params["games"],
        seed=params["seed"],
        on_progress=ctx.progress,
        stop_check=ctx.stopped,
    )
    metrics = {"games": report["games"], "n_predictions": report["n_predictions"]}
    for model in MODELS:
        metrics[f"{model}_top1"] = report[model]["top1"]
        metrics[f"{model}_top3"] = report[model]["top3"]
    phases = [p for p in PHASES if report["by_phase"][p]["n"] > 0]
    for phase in phases:
        metrics[f"predictor_top1_{phase}"] = report["by_phase"][phase]["predictor"]["top1"]

    summary = (
        f"The profiler predicted the opponent's exact move {pct(report['predictor']['top1'])} "
        f"of the time (top-3: {pct(report['predictor']['top3'])}) over "
        f"{report['n_predictions']} predictions, vs {pct(report['static_greedy']['top1'])} "
        f"for a static greedy model and {pct(report['uniform']['top1'])} for uniform guessing."
    )
    if len(phases) >= 2:
        first, last = phases[0], phases[-1]
        summary += (
            f" Top-1 moved from {pct(report['by_phase'][first]['predictor']['top1'])} "
            f"({first}) to {pct(report['by_phase'][last]['predictor']['top1'])} ({last})."
        )

    return result(
        summary=abort_note(ctx) + summary,
        metrics=metrics,
        tables=[
            table(
                "Accuracy by model",
                ["model", "top-1", "top-3"],
                [[m, report[m]["top1"], report[m]["top3"]] for m in MODELS],
            ),
            table(
                "Predictor accuracy by game phase",
                ["phase", "predictions", "predictor top-1", "predictor top-3",
                 "static greedy top-1", "uniform top-1"],
                [
                    [p, report["by_phase"][p]["n"],
                     report["by_phase"][p]["predictor"]["top1"],
                     report["by_phase"][p]["predictor"]["top3"],
                     report["by_phase"][p]["static_greedy"]["top1"],
                     report["by_phase"][p]["uniform"]["top1"]]
                    for p in phases
                ],
            ),
            table(
                "Per-game archetype classification of the subject",
                ["game", "preset", "archetype", "confidence", "moves_observed"],
                [[a["game"], a["preset"], a["archetype"], a["confidence"], a["moves_observed"]]
                 for a in report["archetypes"]],
            ),
        ],
        series=[
            bar("Prediction accuracy by model", list(MODELS),
                {"top-1": [report[m]["top1"] for m in MODELS],
                 "top-3": [report[m]["top3"] for m in MODELS]},
                x_label="model", y_label="accuracy"),
            line("Predictor top-1 accuracy by game phase", phases,
                 {"predictor": [report["by_phase"][p]["predictor"]["top1"] for p in phases],
                  "static greedy": [report["by_phase"][p]["static_greedy"]["top1"] for p in phases],
                  "uniform": [report["by_phase"][p]["uniform"]["top1"] for p in phases]},
                 x_label="phase", y_label="top-1 accuracy"),
        ],
        raw=report,
    )


SPEC = ExperimentSpec(
    name="prediction_accuracy",
    title="Opponent-model prediction accuracy",
    description=(
        "How well does the Profiler predict an opponent's next move? "
        "Compares top-1/top-3 accuracy against uniform and static-greedy "
        "baselines, split by early/mid/late game."
    ),
    report_section="4. Opponent modeling & profiling (A2)",
    estimated="~30 s at defaults",
    params=(
        ParamSpec("games", "int", 10, "Games to evaluate (presets alternate)", 1, 500),
        ParamSpec("seed", "int", 0, "Base random seed", 0, 1_000_000),
    ),
    run=run,
)
