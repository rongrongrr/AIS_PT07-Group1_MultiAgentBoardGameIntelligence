"""Does the opponent model help against opponents it cannot describe exactly?"""

from __future__ import annotations

from typing import List

from tiles.agents.profiler import BasicProfiler
from tiles.agents.profiler.habits import ExtendedProfiler
from tiles.agents.tacticians.styles import style_names
from tiles.experiments.registry import ExperimentSpec, ParamSpec
from tiles.sim.match import MatchConfig
from tiles.sim.study import mean_ci, run_match_with_stats, wilson
from tiles.sim.style_eval import evaluate_style_prediction

from ._common import abort_note, bar, result, table

BOTS = ("mcts", "mcts_profiled")
DEFAULT_STYLES = "colour_loyal,centre_averse,low_rows,noisy"


def _styles(text: str) -> List[str]:
    out: List[str] = []
    for n in str(text).split(","):
        n = n.strip()
        if n and n not in out:
            out.append(n)
    return out


def _profiler(params: dict):
    """A fresh Profiler instance, or None to use the default one named in the match."""
    if params["profiler"] == "extended":
        return ExtendedProfiler(habit_rate=params["habit_rate"])
    return None


def validate(params: dict) -> None:
    if params["profiler"] not in ("basic", "extended"):
        raise ValueError("profiler must be 'basic' or 'extended'")
    names = _styles(params["styles"])
    if not names:
        raise ValueError("styles must list at least one style")
    unknown = [n for n in names if n not in style_names()]
    if unknown:
        raise ValueError(f"unknown style(s) {unknown}; available: {style_names()}")


def run(params: dict, ctx) -> dict:
    styles = _styles(params["styles"])
    n = params["games_per_cell"]
    sims = params["simulations"]
    seed = params["seed"]
    total = len(styles) * len(BOTS) * n
    done = 0
    stats: List[dict] = []
    cells = {}
    for si, style in enumerate(styles):
        for bot in BOTS:
            cell = {"wins": [], "margin": [], "ms": []}
            for g in range(n):
                if ctx.stopped():
                    break
                seat = g % 2
                players = [{"name": "opponent", "tactician": f"style_{style}", "config": {"seed": seed + si * 1000 + g}}]
                players.insert(seat, {"name": "subject", "tactician": bot, "config": {"simulations": sims}})
                labels = ["opponent", "opponent"]
                labels[seat] = "subject"
                # The same deals for both bots (same seed and seat), so they can be compared game by game.
                config = MatchConfig(players=players, profiler="basic", explainer=None, seed=seed + si * 1000 + g)
                match, game = run_match_with_stats(
                    config, labels, game_id=len(stats), setting=f"{style}/{bot}", keep_records=True,
                    profiler=_profiler(params),
                )
                stats.append(game)
                me, them = match.scores[seat], match.scores[1 - seat]
                cell["wins"].append(1.0 if match.winner == seat else (0.5 if match.winner is None and me == them else 0.0))
                cell["margin"].append(me - them)
                cell["ms"].extend(r["timing"]["decide_ms"] for r in match.records if r.get("player_name") == "subject")
                done += 1
                ctx.progress(done, total, f"vs {style}: {bot} game {g + 1}/{n}")
            cells[(style, bot)] = cell

    pred = {}
    for style in styles:
        if ctx.stopped():
            break
        pred[style] = evaluate_style_prediction(
            style, games=params["prediction_games"], seed=seed + 7, stop_check=ctx.stopped,
            profiler_factory=(lambda: _profiler(params)) if params["profiler"] == "extended" else BasicProfiler,
        )

    rows, effect, prediction = [], [], []
    for style in styles:
        for bot in BOTS:
            c = cells.get((style, bot))
            if not c or not c["wins"]:
                continue
            k, m = sum(c["wins"]), len(c["wins"])
            lo, hi = wilson(k, m)
            mm, mh = mean_ci(c["margin"])
            rows.append([style, bot, m, round(k), round(k / m, 3), round(lo, 3), round(hi, 3), round(mm, 2), round(mh, 2),
                         round(sum(c["ms"]) / len(c["ms"]), 1) if c["ms"] else 0.0])
        a, b = cells.get((style, "mcts")), cells.get((style, "mcts_profiled"))
        if a and b and len(a["wins"]) == len(b["wins"]) and len(a["wins"]) > 1:
            dw = mean_ci([y - x for x, y in zip(a["wins"], b["wins"])])
            dm = mean_ci([y - x for x, y in zip(a["margin"], b["margin"])])
            effect.append([style, round(dw[0], 3), round(dw[1], 3), round(dm[0], 2), round(dm[1], 2)])
        p = pred.get(style)
        if p and p["n"]:
            prediction.append([style, p["n"], round(p["profiler_top1"] / p["n"], 3), round(p["profiler_top3"] / p["n"], 3),
                               round(p["static_top1"] / p["n"], 3), round(p["static_top3"] / p["n"], 3),
                               round(p["uniform_top1"] / p["n"], 3)])

    gain = [e for e in effect if abs(e[1]) > e[2]]
    summary = (
        f"mcts_profiled against {len(styles)} opponent styles: win-rate difference from plain mcts "
        + ", ".join(f"{e[0]} {e[1]:+.1%}±{e[2]:.1%}" for e in effect)
        + (f"; clearly different from zero for {', '.join(e[0] for e in gain)}." if gain else "; none is clearly different from zero.")
    ) if effect else "No games were played."

    return result(
        summary=abort_note(ctx) + summary,
        metrics={"games": len(stats), **{f"win_diff_{e[0]}": e[1] for e in effect}},
        tables=[
            table("Win rate against each style",
                  ["style", "bot", "games", "wins", "win_rate", "ci_low", "ci_high", "avg_margin", "margin_ci", "avg_decision_ms"], rows),
            table("Opponent-model effect (mcts_profiled minus mcts, paired by game)",
                  ["style", "win_diff", "win_diff_ci", "margin_diff", "margin_diff_ci"], effect),
            table("Next-move prediction on these opponents",
                  ["style", "predictions", "profiler_top1", "profiler_top3", "static_top1", "static_top3", "uniform_top1"], prediction),
        ],
        series=[
            bar("Win rate by style", [r[0] + "/" + r[1] for r in rows], {"win_rate": [r[4] for r in rows]},
                x_label="style / bot", y_label="win rate"),
        ],
        raw={"game_stats": stats, "params": dict(params)},
    )


SPEC = ExperimentSpec(
    name="opponent_styles",
    title="Opponent model against odd opponents",
    description=(
        "Plain MCTS and MCTS with the opponent model play opponents that add a habit the Profiler's "
        "seven-weight model cannot describe: a favourite colour, a dislike of the centre, a liking for "
        "the short pattern lines, or occasional random moves. Both bots get the same deals, so they are "
        "compared game by game. Also reports how well the Profiler predicts each opponent's next move."
    ),
    report_section="10.1 (continued)",
    estimated="~20 min at defaults",
    params=(
        ParamSpec("games_per_cell", "int", 50, "Games per bot and style", 2, 500),
        ParamSpec("simulations", "int", 100, "MCTS simulations per move", 10, 2000),
        ParamSpec("prediction_games", "int", 20, "Games for the prediction check per style", 1, 200),
        ParamSpec("seed", "int", 0, "Base random seed", 0, 1_000_000),
        ParamSpec("styles", "str", DEFAULT_STYLES, "Comma-separated opponent styles"),
        ParamSpec("profiler", "str", "basic", "Profiler used: basic, or extended (also learns colour, centre and row habits)"),
        ParamSpec("habit_rate", "float", 0.25, "Step size for the habit weights of the extended Profiler", 0.05, 3.0),
    ),
    run=run,
    validate=validate,
)
