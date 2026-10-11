"""Controlled studies: heuristic variants and player-count scaling.

Everything here plays full games through the normal ``MatchRunner`` and
extracts one uniform per-game, per-player record, so every game leaves
the same statistics behind whatever was being compared:

* result: score, rank, win / shared win
* scoring anatomy: tiling points, floor penalties, end-game row, column
  and colour bonuses
* behaviour: moves, share of moves to the floor, share taken from the
  centre, first-player-token pick-ups
* cost: mean decision time

Seats are rotated so first-move advantage cancels out, and every setting
is dealt from the same seed sequence (common random numbers), so two
settings differ only in the thing being varied.
"""

from __future__ import annotations

import math
import statistics
from typing import Callable, Dict, List, Optional, Sequence

from tiles.agents.tacticians.heuristics import DEFAULT_WEIGHTS
from tiles.sim.match import MatchConfig, MatchRunner

#: Named weight sets for the greedy Tactician, each one a hypothesis about
#: what matters in Azul. Missing keys keep the baseline value.
HEURISTICS: Dict[str, Dict[str, float]] = {
    "baseline": {},
    "myopic": {  # only points now and the floor: no planning at all
        "line_progress": 0.0,
        "near_completion": 0.0,
        "first_player": 0.0,
        "bonus_potential": 0.0,
        "denial": 0.0,
    },
    "points_first": {"immediate_points": 5.0, "bonus_potential": 0.3},
    "builder": {"line_progress": 2.0, "near_completion": 2.0},
    "bonus_hunter": {"bonus_potential": 2.0},
    "floor_averse": {"floor_penalty": 2.5},
    "floor_tolerant": {"floor_penalty": 0.4},
    "tempo_fpt": {"first_player": 2.0},
    "denial_heavy": {"denial": 1.5},
    "no_denial": {"denial": 0.0},
    # Extreme versions of the same ideas, to see whether a stronger push helps.
    "floor_blind": {"floor_penalty": 0.0},
    "bonus_extreme": {"bonus_potential": 5.0},
    "denial_extreme": {"denial": 4.0},
    "tempo_extreme": {"first_player": 4.0},
    "line_focus_extreme": {"line_progress": 4.0, "near_completion": 4.0},
    # New information, not just new weights (docs/FINAL_REPORT.md, section 10.8).
    "floor_outlook": {"floor_outlook": 1.0},
    "floor_outlook_strong": {"floor_outlook": 2.5},
    "round_end": {"round_end_feasibility": 1.0},
    "round_end_strong": {"round_end_feasibility": 2.5},
    "table_aware": {},
    "combined": {"floor_outlook": 1.0, "round_end_feasibility": 1.0},
    # Second round of new information (docs/FINAL_REPORT.md, section 10.8).
    "spoil": {"spoil": 1.0},
    "spoil_strong": {"spoil": 3.0},
    "bonus_reach": {"bonus_reach": 1.0},
    "bonus_reach_strong": {"bonus_reach": 2.5},
    "endgame": {},
    "best_of_all": {"round_end_feasibility": 1.0, "bonus_reach": 1.0},
}

#: Variants that also set the first-player-token value from the table size.
TABLE_AWARE_VARIANTS = frozenset({"table_aware", "combined", "best_of_all"})

#: Variants that also switch to closing-round weights near the end.
ENDGAME_VARIANTS = frozenset({"endgame", "best_of_all"})


def heuristic_weights(name: str) -> Dict[str, float]:
    if name not in HEURISTICS:
        raise ValueError(f"unknown heuristic {name!r}; available: {sorted(HEURISTICS)}")
    return {**DEFAULT_WEIGHTS, **HEURISTICS[name]}


# ---------------------------------------------------------------------------
# One game
# ---------------------------------------------------------------------------


def play_game(
    seats: Sequence[dict],
    seed: int,
    game_id: int = 0,
    setting: str = "",
) -> dict:
    """Play one game and return its per-game statistics.

    ``seats`` is ``[{"label", "tactician", "config"}...]`` in seat order.
    """
    n = len(seats)
    config = MatchConfig(
        players=[
            {"name": f"S{i + 1}", "tactician": s["tactician"], "config": s.get("config") or {}}
            for i, s in enumerate(seats)
        ],
        profiler=None,
        explainer=None,
        seed=seed,
    )
    return run_match_with_stats(config, [s["label"] for s in seats], game_id, setting)[1]


def run_match_with_stats(
    config: MatchConfig,
    labels: Sequence[str],
    game_id: int = 0,
    setting: str = "",
    keep_records: bool = False,
) -> tuple:
    """Play ``config`` and return ``(match_result, per_game_statistics)``.

    The statistics are the same for every experiment that plays games, so
    their per-game files can be read together. ``labels`` names each seat in
    the output; ``keep_records`` is passed on to the match runner.
    """
    n = len(config.players)
    seed = config.seed
    moves = [0] * n
    floor_moves = [0] * n
    center_moves = [0] * n
    fpt = [0] * n
    decide_ms: List[List[float]] = [[] for _ in range(n)]
    tiling_points = [0] * n
    floor_penalty = [0] * n
    tiles_scored = [0] * n
    bonuses: List[dict] = [{"rows": 0, "cols": 0, "colors": 0, "points": 0}] * n

    def on_event(event: dict) -> None:
        nonlocal bonuses
        kind = event["type"]
        if kind == "move":
            rec = event["record"]
            i = rec["player_index"]
            moves[i] += 1
            act = rec["action"]
            if act["destination"] == "floor":
                floor_moves[i] += 1
            if act["source_type"] == "center":
                center_moves[i] += 1
                before = rec.get("state_before") or {}
                if "firstPlayer" in (before.get("center_pool") or []):
                    fpt[i] += 1
            ms = (rec.get("timing") or {}).get("decide_ms")
            if ms is not None:
                decide_ms[i].append(ms)
        elif kind == "round":
            res = event["result"]
            for t in res["tilings"]:
                tiling_points[t["player_index"]] += t["points"]
                tiles_scored[t["player_index"]] += 1
            for i, p in enumerate(res.get("floor_penalties") or []):
                floor_penalty[i] += p
        elif kind == "game_over" and event.get("bonuses"):
            bonuses = event["bonuses"]

    match = MatchRunner(config, on_event=on_event, keep_records=keep_records).run()
    scores = match.scores
    top = max(scores)
    winners = [i for i, s in enumerate(scores) if s == top]
    solo_win = match.winner is not None
    order = sorted(range(n), key=lambda i: -scores[i])

    players = []
    for i in range(n):
        mv = max(moves[i], 1)
        players.append(
            {
                "seat": i + 1,
                "label": labels[i],
                "tactician": config.players[i]["tactician"],
                "score": scores[i],
                "rank": 1 + sum(1 for s in scores if s > scores[i]),
                "won": 1.0 if solo_win and match.winner == i else 0.0,
                "shared": 1.0 if (not solo_win and i in winners) else 0.0,
                "tiling_points": tiling_points[i],
                "tiles_placed": tiles_scored[i],
                "floor_penalty": floor_penalty[i],
                "bonus_rows": bonuses[i]["rows"],
                "bonus_cols": bonuses[i]["cols"],
                "bonus_colors": bonuses[i]["colors"],
                "bonus_points": bonuses[i]["points"],
                "moves": moves[i],
                "floor_move_share": round(floor_moves[i] / mv, 4),
                "center_move_share": round(center_moves[i] / mv, 4),
                "fpt_pickups": fpt[i],
                "avg_decide_ms": round(statistics.fmean(decide_ms[i]), 3) if decide_ms[i] else 0.0,
            }
        )
    return match, {
        "game": game_id,
        "setting": setting,
        "num_players": n,
        "seed": seed,
        "steps": match.steps,
        "rounds": match.rounds,
        "duration_s": round(match.duration_s, 3),
        "scores": scores,
        "winner_seat": (match.winner + 1) if solo_win else None,
        "finish_order": [i + 1 for i in order],
        "players": players,
    }


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------


def mean_ci(values: Sequence[float]) -> tuple:
    """(mean, half-width of the 95% normal-approximation interval)."""
    if not values:
        return 0.0, 0.0
    m = statistics.fmean(values)
    if len(values) < 2:
        return m, 0.0
    return m, 1.96 * statistics.stdev(values) / math.sqrt(len(values))


def wilson(successes: float, n: int, z: float = 1.96) -> tuple:
    """Wilson score interval (low, high) for a proportion."""
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


PLAYER_STATS = (
    "score",
    "tiling_points",
    "floor_penalty",
    "bonus_points",
    "bonus_rows",
    "bonus_cols",
    "bonus_colors",
    "floor_move_share",
    "center_move_share",
    "fpt_pickups",
    "avg_decide_ms",
)


def summarise(games: List[dict], label: Optional[str] = None, tactician: Optional[str] = None) -> dict:
    """Aggregate every game's rows for one label (or tactician) into one row."""
    rows = [
        p
        for g in games
        for p in g["players"]
        if (label is None or p["label"] == label) and (tactician is None or p["tactician"] == tactician)
    ]
    n = len(rows)
    out: dict = {"label": label or tactician or "all", "player_games": n}
    for key in PLAYER_STATS:
        m, ci = mean_ci([r[key] for r in rows])
        out[key] = round(m, 3)
        out[f"{key}_ci"] = round(ci, 3)
    wins = sum(r["won"] for r in rows)
    shared = sum(r["shared"] for r in rows)
    lo, hi = wilson(wins + 0.5 * shared, n)
    out.update(
        win_rate=round((wins + 0.5 * shared) / n, 4) if n else 0.0,
        win_ci_low=round(lo, 4),
        win_ci_high=round(hi, 4),
        avg_rank=round(statistics.fmean([r["rank"] for r in rows]), 3) if rows else 0.0,
    )
    return out


# ---------------------------------------------------------------------------
# Study drivers
# ---------------------------------------------------------------------------

Progress = Optional[Callable[[int, int, str], None]]
Stop = Optional[Callable[[], bool]]


def _tactician_seat(label: str, tactician: str, config: Optional[dict] = None) -> dict:
    return {"label": label, "tactician": tactician, "config": config or {}}


def heuristic_study(
    variants: Sequence[str],
    num_players: int,
    games: int,
    seed: int,
    on_progress: Progress = None,
    stop_check: Stop = None,
    opponent: str = "greedy",
    opponent_config: Optional[dict] = None,
) -> List[dict]:
    """Each variant sits at a table with ``num_players - 1`` opponents
    (baseline greedy unless ``opponent`` says otherwise). Seats rotate;
    deals are shared across variants."""
    out: List[dict] = []
    total = len(variants) * games
    done = 0
    for variant in variants:
        for g in range(games):
            if stop_check and stop_check():
                return out
            focal = g % num_players
            seats = [
                _tactician_seat(
                    "focal",
                    "greedy",
                    {"weights": heuristic_weights(variant), "table_aware": variant in TABLE_AWARE_VARIANTS,
                     "endgame_aware": variant in ENDGAME_VARIANTS},
                )
                if i == focal
                else _tactician_seat("baseline", opponent, opponent_config)
                for i in range(num_players)
            ]
            game = play_game(seats, seed + g, game_id=len(out), setting=variant)
            game["focal_seat"] = focal + 1
            out.append(game)
            done += 1
            if on_progress:
                on_progress(done, total, f"{variant}: game {g + 1}/{games} ({num_players} players)")
    return out


def scaling_study(
    tactician: str,
    config: dict,
    player_counts: Sequence[int],
    games: int,
    seed: int,
    opponent: str = "random",
    modes: Sequence[str] = ("self", "field"),
    on_progress: Progress = None,
    stop_check: Stop = None,
) -> List[dict]:
    """Two table types for every player count:

    * ``self``: every seat plays ``tactician`` (how the game itself
      scales: scores, length, seat advantage);
    * ``field``: one ``tactician`` against ``opponent`` fillers (how the
      Tactician's edge changes as the table gets more crowded; chance is
      ``1 / players``).
    """
    out: List[dict] = []
    total = len(player_counts) * games * len(modes)
    done = 0
    for n in player_counts:
        for mode in modes:
            for g in range(games):
                if stop_check and stop_check():
                    return out
                focal = g % n
                if mode == "self":
                    seats = [_tactician_seat("focal", tactician, config) for _ in range(n)]
                else:
                    seats = [
                        _tactician_seat("focal", tactician, config)
                        if i == focal
                        else _tactician_seat("filler", opponent)
                        for i in range(n)
                    ]
                game = play_game(seats, seed + g, game_id=len(out), setting=f"{mode}-{n}p")
                game.update(mode=mode, focal_seat=focal + 1 if mode == "field" else None)
                out.append(game)
                done += 1
                if on_progress:
                    on_progress(done, total, f"{tactician} {mode} {n}p: game {g + 1}/{games}")
    return out
