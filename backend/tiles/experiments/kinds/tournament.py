"""Tactician strength ladder — round-robin tournament with Elo (A3)."""

from __future__ import annotations

from typing import Dict, List

from tiles.agents.tacticians import TACTICIANS
from tiles.experiments.registry import ExperimentSpec, ParamSpec
from tiles.sim.tournament import run_tournament

from ._common import abort_note, bar, matrix, result, table

DEFAULT_ENTRANTS = "random,greedy,minimax,mcts,mcts_profiled"


def _parse_entrants(text: str) -> List[str]:
    names = [n.strip() for n in str(text).split(",") if n.strip()]
    seen: List[str] = []
    for name in names:
        if name not in seen:
            seen.append(name)
    return seen


def validate(params: dict) -> None:
    names = _parse_entrants(params["entrants"])
    if len(names) < 2:
        raise ValueError("entrants must list at least two distinct tacticians")
    unknown = [n for n in names if n not in TACTICIANS]
    if unknown:
        raise ValueError(
            f"unknown tactician(s) {unknown}; available: {sorted(TACTICIANS)}"
        )


def run(params: dict, ctx) -> dict:
    names = _parse_entrants(params["entrants"])
    entrants = []
    for name in names:
        config = {"simulations": params["simulations"]} if name.startswith("mcts") else {}
        entrants.append({"name": name, "tactician": name, "config": config})

    outcome = run_tournament(
        entrants,
        games_per_pair=params["games_per_pair"],
        seed=params["seed"],
        on_progress=ctx.progress,
        stop_check=ctx.stopped,
    )
    standings = outcome.to_dict()["standings"]
    games = outcome.games

    # Head-to-head wins: rows = winner, cols = loser.
    wins: Dict[str, Dict[str, int]] = {a: {b: 0 for b in names} for a in names}
    for game in games:
        if game["winner"] is None:
            continue
        loser = [p for p in game["players"] if p != game["winner"]][0]
        wins[game["winner"]][loser] += 1

    metrics = {f"elo_{s['name']}": s["elo"] for s in standings}
    metrics["games_played"] = len(games)
    if standings:
        top = standings[0]
        summary = (
            f"{top['name']} tops the ladder at Elo {top['elo']:.0f} "
            f"({top['wins']}W-{top['losses']}L-{top['ties']}T, "
            f"avg {top['avg_score']:.1f} pts) over {len(games)} games "
            f"between {len(names)} tacticians."
        )
    else:
        summary = "No games were played."

    return result(
        summary=abort_note(ctx) + summary,
        metrics=metrics,
        tables=[
            table(
                "Standings",
                ["player", "elo", "games", "wins", "losses", "ties", "win_rate", "avg_score"],
                [
                    [s["name"], s["elo"], s["games"], s["wins"], s["losses"],
                     s["ties"], s["win_rate"], s["avg_score"]]
                    for s in standings
                ],
            ),
            table(
                "Games",
                ["game", "first", "second", "score", "winner", "steps"],
                [
                    [g["game"], g["players"][0], g["players"][1],
                     f"{g['scores'][0]}-{g['scores'][1]}", g["winner"] or "tie", g["steps"]]
                    for g in games
                ],
            ),
        ],
        series=[
            bar("Elo rating", [s["name"] for s in standings],
                {"elo": [s["elo"] for s in standings]},
                x_label="tactician", y_label="Elo"),
            matrix("Head-to-head wins (row beat column)", names, names,
                   [[wins[a][b] for b in names] for a in names],
                   x_label="loser", y_label="winner"),
        ],
        raw={
            "standings": standings,
            "games": games,
            "game_stats": outcome.game_stats,
            "params": dict(params),
        },
    )


SPEC = ExperimentSpec(
    name="tournament",
    title="Tactician tournament",
    description=(
        "Round-robin between tacticians with Elo ratings and a "
        "head-to-head matrix. Seats alternate so first-move advantage "
        "cancels out."
    ),
    report_section="5. Strategic search (A3 strength ladder)",
    estimated="~1-2 min at defaults",
    params=(
        ParamSpec("games_per_pair", "int", 2, "Games per pairing", 1, 100),
        ParamSpec("simulations", "int", 100, "MCTS simulations per move", 10, 2000),
        ParamSpec("seed", "int", 0, "Base random seed", 0, 1_000_000),
        ParamSpec("entrants", "str", DEFAULT_ENTRANTS,
                  "Comma-separated tactician names"),
    ),
    run=run,
    validate=validate,
)
