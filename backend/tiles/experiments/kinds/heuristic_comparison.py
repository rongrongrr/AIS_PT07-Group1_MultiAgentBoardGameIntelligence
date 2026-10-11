"""Heuristic variants against the baseline, at a chosen table size."""

from __future__ import annotations

from typing import List

from tiles.agents.tacticians import TACTICIANS
from tiles.experiments.registry import ExperimentSpec, ParamSpec
from tiles.sim.study import HEURISTICS, heuristic_study, summarise

from ._common import abort_note, bar, result, table

DEFAULT_VARIANTS = ",".join(HEURISTICS)


def _parse(text: str) -> List[str]:
    names: List[str] = []
    for n in str(text).split(","):
        n = n.strip()
        if n and n not in names:
            names.append(n)
    return names


def validate(params: dict) -> None:
    names = _parse(params["variants"])
    if params["opponent"] not in TACTICIANS:
        raise ValueError(f"unknown opponent {params['opponent']!r}; available: {sorted(TACTICIANS)}")
    if not names:
        raise ValueError("variants must list at least one heuristic")
    unknown = [n for n in names if n not in HEURISTICS]
    if unknown:
        raise ValueError(f"unknown heuristic(s) {unknown}; available: {sorted(HEURISTICS)}")


def run(params: dict, ctx) -> dict:
    names = _parse(params["variants"])
    n = params["num_players"]
    games = heuristic_study(
        names,
        num_players=n,
        games=params["games_per_variant"],
        seed=params["seed"],
        on_progress=ctx.progress,
        stop_check=ctx.stopped,
        opponent=params["opponent"],
        opponent_config=(
            {"simulations": params["opponent_simulations"]} if params["opponent"].startswith("mcts") else {}
        ),
    )
    rows = []
    for name in names:
        subset = [g for g in games if g["setting"] == name]
        if subset:
            rows.append((name, summarise(subset, label="focal"), summarise(subset, label="baseline")))
    rows.sort(key=lambda r: -r[1]["win_rate"])
    chance = 1 / n

    summary = "No games were played."
    if rows:
        best = rows[0]
        summary = (
            f"{len(games)} games at {n} players. Best variant: {best[0]} "
            f"(win rate {best[1]['win_rate']:.0%} vs {chance:.0%} for an equal player, "
            f"mean score {best[1]['score']:.1f} vs {best[2]['score']:.1f} for the baseline seats)."
        )

    return result(
        summary=abort_note(ctx) + summary,
        metrics={"games_played": len(games), "num_players": n, **{f"win_rate_{r[0]}": r[1]["win_rate"] for r in rows}},
        tables=[
            table(
                "Variants vs baseline",
                ["variant", "win_rate", "win_ci_low", "win_ci_high", "score", "baseline_score",
                 "floor_penalty", "bonus_points", "tiling_points", "floor_move_share", "fpt_pickups"],
                [
                    [name, f["win_rate"], f["win_ci_low"], f["win_ci_high"], f["score"], b["score"],
                     f["floor_penalty"], f["bonus_points"], f["tiling_points"],
                     f["floor_move_share"], f["fpt_pickups"]]
                    for name, f, b in rows
                ],
            )
        ],
        series=[
            bar(f"Win rate at {n} players (chance = {chance:.0%})", [r[0] for r in rows],
                {"win_rate": [r[1]["win_rate"] for r in rows]}, x_label="variant", y_label="win rate"),
            bar("Mean score", [r[0] for r in rows],
                {"variant": [r[1]["score"] for r in rows], "baseline": [r[2]["score"] for r in rows]},
                x_label="variant", y_label="points"),
        ],
        raw={"games": games, "params": dict(params)},
    )


SPEC = ExperimentSpec(
    name="heuristic_comparison",
    title="Heuristic comparison",
    description=(
        "Each heuristic variant (a weight set for the greedy Tactician) plays against "
        "baseline greedy players at the chosen table size. Seats rotate and all variants "
        "share the same deals. Every game's per-player statistics are kept in the result."
    ),
    report_section="Heuristic study",
    estimated="~1 min at defaults",
    params=(
        ParamSpec("games_per_variant", "int", 100, "Games per variant", 2, 2000),
        ParamSpec("num_players", "int", 2, "Players at the table", 2, 4),
        ParamSpec("seed", "int", 0, "Base random seed", 0, 1_000_000),
        ParamSpec("variants", "str", DEFAULT_VARIANTS, "Comma-separated heuristic names"),
        ParamSpec("opponent", "str", "greedy", "Tactician in the other seats (greedy = the baseline)"),
        ParamSpec("opponent_simulations", "int", 50, "MCTS simulations per move for the opponent", 10, 2000),
    ),
    run=run,
    validate=validate,
)
