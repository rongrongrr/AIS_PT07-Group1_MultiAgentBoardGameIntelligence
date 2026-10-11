"""One Tactician across 2, 3 and 4 player tables."""

from __future__ import annotations

from typing import List

from tiles.agents.tacticians import TACTICIANS
from tiles.experiments.registry import ExperimentSpec, ParamSpec
from tiles.sim.study import mean_ci, scaling_study, summarise

from ._common import abort_note, bar, line, result, table


def _counts(text: str) -> List[int]:
    out: List[int] = []
    for part in str(text).split(","):
        part = part.strip()
        if part:
            out.append(int(part))
    return out


def _modes(text: str) -> List[str]:
    return [m.strip() for m in str(text).split(",") if m.strip()]


def validate(params: dict) -> None:
    if not _modes(params["modes"]) or any(m not in ("self", "field") for m in _modes(params["modes"])):
        raise ValueError("modes must be 'self', 'field' or 'self,field'")
    if params["tactician"] not in TACTICIANS:
        raise ValueError(f"unknown tactician {params['tactician']!r}; available: {sorted(TACTICIANS)}")
    if params["opponent"] not in TACTICIANS:
        raise ValueError(f"unknown opponent {params['opponent']!r}; available: {sorted(TACTICIANS)}")
    try:
        counts = _counts(params["player_counts"])
    except ValueError:
        raise ValueError("player_counts must be comma-separated integers") from None
    if not counts or any(c < 2 or c > 4 for c in counts):
        raise ValueError("player_counts must be values between 2 and 4")


def run(params: dict, ctx) -> dict:
    name = params["tactician"]
    config = {"simulations": params["simulations"]} if name.startswith("mcts") else {}
    counts = _counts(params["player_counts"])
    games = scaling_study(
        name,
        config,
        counts,
        games=params["games_per_setting"],
        seed=params["seed"],
        opponent=params["opponent"],
        modes=_modes(params["modes"]),
        on_progress=ctx.progress,
        stop_check=ctx.stopped,
    )

    self_rows, field_rows = [], []
    for n in counts:
        mine = [g for g in games if g["setting"] == f"self-{n}p"]
        if mine:
            s = summarise(mine, label="focal")
            seat_wins = [
                sum(1 for g in mine if g["winner_seat"] == seat) / len(mine) for seat in range(1, n + 1)
            ]
            spread, _ = mean_ci([max(g["scores"]) - min(g["scores"]) for g in mine])
            self_rows.append(
                [n, len(mine), s["score"], s["score_ci"], s["floor_penalty"], s["bonus_points"],
                 round(sum(g["steps"] for g in mine) / len(mine), 1),
                 round(sum(g["rounds"] for g in mine) / len(mine), 2), round(spread, 1),
                 round(seat_wins[0], 3), round(seat_wins[-1], 3)]
            )
        theirs = [g for g in games if g["setting"] == f"field-{n}p"]
        if theirs:
            f = summarise(theirs, label="focal")
            o = summarise(theirs, label="filler")
            field_rows.append(
                [n, len(theirs), f["win_rate"], f["win_ci_low"], f["win_ci_high"], round(1 / n, 3),
                 round(f["win_rate"] / (1 / n), 2), f["score"], o["score"], f["floor_penalty"], f["avg_decide_ms"]]
            )

    summary = "No games were played."
    if field_rows:
        lift = ", ".join(f"{r[0]}p: {r[2]:.0%} (chance {r[5]:.0%})" for r in field_rows)
        summary = f"{name} vs {params['opponent']} fillers, win rate by table size: {lift}."

    return result(
        summary=abort_note(ctx) + summary,
        metrics={"games_played": len(games), **{f"field_win_rate_{r[0]}p": r[2] for r in field_rows}},
        tables=[
            table(
                f"Self-play: every seat plays {name}",
                ["players", "games", "mean_score", "score_ci", "floor_penalty", "bonus_points",
                 "mean_steps", "mean_rounds", "winner_margin_range", "seat1_win_rate", "last_seat_win_rate"],
                self_rows,
            ),
            table(
                f"{name} against {params['opponent']} fillers",
                ["players", "games", "win_rate", "ci_low", "ci_high", "chance", "lift_over_chance",
                 "score", "filler_score", "floor_penalty", "avg_decide_ms"],
                field_rows,
            ),
        ],
        series=[
            line("Win rate against fillers vs chance", [f"{r[0]}p" for r in field_rows],
                 {"win_rate": [r[2] for r in field_rows], "chance": [r[5] for r in field_rows]},
                 x_label="players", y_label="win rate"),
            bar("Mean score per player in self-play", [f"{r[0]}p" for r in self_rows],
                {"score": [r[2] for r in self_rows]}, x_label="players", y_label="points"),
        ],
        raw={"games": games, "params": dict(params)},
    )


SPEC = ExperimentSpec(
    name="player_count_scaling",
    title="Player-count scaling",
    description=(
        "One Tactician at 2, 3 and 4 player tables: self-play (how scores, game length and "
        "seat advantage change) and against filler opponents (how its edge over chance changes). "
        "Every game's per-player statistics are kept in the result."
    ),
    report_section="Heuristic study",
    estimated="~1 min for greedy; minutes for MCTS",
    params=(
        ParamSpec("tactician", "str", "greedy", "Tactician under test"),
        ParamSpec("opponent", "str", "random", "Filler opponent in field games"),
        ParamSpec("player_counts", "str", "2,3,4", "Comma-separated table sizes (2-4)"),
        ParamSpec("modes", "str", "self,field", "Table types: self, field or both"),
        ParamSpec("games_per_setting", "int", 100, "Games per table type and size", 2, 2000),
        ParamSpec("simulations", "int", 100, "MCTS simulations per move", 10, 2000),
        ParamSpec("seed", "int", 0, "Base random seed", 0, 1_000_000),
    ),
    run=run,
    validate=validate,
)
