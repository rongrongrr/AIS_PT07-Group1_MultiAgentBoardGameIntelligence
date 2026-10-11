"""Round-robin tournaments with Elo tracking (report roadmap item).

``run_tournament`` accepts optional ``on_progress(done, total, message)``
and ``stop_check()`` hooks so the experiment runner can stream progress
and abort between games; the existing ``on_game`` callback is kept.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from tiles.sim.match import MatchConfig
from tiles.sim.study import run_match_with_stats

DEFAULT_ELO = 1200.0
K_FACTOR = 32.0


@dataclass
class Standing:
    name: str
    spec: dict
    elo: float = DEFAULT_ELO
    wins: int = 0
    losses: int = 0
    ties: int = 0
    points_for: int = 0
    points_against: int = 0

    def to_dict(self) -> dict:
        games = self.wins + self.losses + self.ties
        return {
            "name": self.name,
            "tactician": self.spec.get("tactician"),
            "elo": round(self.elo, 1),
            "games": games,
            "wins": self.wins,
            "losses": self.losses,
            "ties": self.ties,
            "win_rate": round(self.wins / games, 3) if games else 0.0,
            "avg_score": (
                round(self.points_for / games, 1) if games else 0.0
            ),
        }


def _elo_update(a: Standing, b: Standing, result_a: float) -> None:
    expected_a = 1.0 / (1.0 + 10 ** ((b.elo - a.elo) / 400.0))
    a.elo += K_FACTOR * (result_a - expected_a)
    b.elo += K_FACTOR * ((1.0 - result_a) - (1.0 - expected_a))


@dataclass
class TournamentResult:
    standings: List[Standing]
    games: List[dict] = field(default_factory=list)
    #: Per-game, per-player statistics (see ``tiles.sim.study``).
    game_stats: List[dict] = field(default_factory=list)

    def table(self) -> str:
        rows = sorted(self.standings, key=lambda s: -s.elo)
        header = f"{'player':<24}{'elo':>7}{'W':>4}{'L':>4}{'T':>4}{'avg pts':>9}"
        lines = [header, "-" * len(header)]
        for s in rows:
            d = s.to_dict()
            lines.append(
                f"{d['name']:<24}{d['elo']:>7.1f}{d['wins']:>4}{d['losses']:>4}"
                f"{d['ties']:>4}{d['avg_score']:>9.1f}"
            )
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "standings": [
                s.to_dict()
                for s in sorted(self.standings, key=lambda x: -x.elo)
            ],
            "games": self.games,
        }


def run_tournament(
    entrants: List[dict],
    games_per_pair: int = 4,
    seed: int = 0,
    profiler: Optional[str] = "basic",
    on_game=None,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_check: Optional[Callable[[], bool]] = None,
) -> TournamentResult:
    """Round-robin between entrant specs.

    Each entrant: ``{"name": ..., "tactician": ..., "config": {...}}``.
    Seats alternate so first-move advantage cancels out.
    """
    standings: Dict[str, Standing] = {
        e["name"]: Standing(name=e["name"], spec=e) for e in entrants
    }
    result = TournamentResult(standings=list(standings.values()))

    pairs = list(itertools.combinations(entrants, 2))
    total = len(pairs) * games_per_pair
    game_no = 0
    for a, b in pairs:
        for g in range(games_per_pair):
            if stop_check is not None and stop_check():
                return result
            first, second = (a, b) if g % 2 == 0 else (b, a)
            config = MatchConfig(
                players=[dict(first), dict(second)],
                profiler=profiler,
                explainer=None,
                seed=seed + game_no,
            )
            match, stats = run_match_with_stats(
                config, [first["name"], second["name"]], game_id=game_no, setting="tournament"
            )
            result.game_stats.append(stats)
            names = [first["name"], second["name"]]
            tie = match.winner is None  # shared win (score and rows tied)
            if not tie:
                winner_name = names[match.winner]
                loser_name = names[1 - match.winner]

            sa, sb = standings[names[0]], standings[names[1]]
            sa.points_for += match.scores[0]
            sa.points_against += match.scores[1]
            sb.points_for += match.scores[1]
            sb.points_against += match.scores[0]
            if tie:
                sa.ties += 1
                sb.ties += 1
                _elo_update(sa, sb, 0.5)
            else:
                standings[winner_name].wins += 1
                standings[loser_name].losses += 1
                _elo_update(
                    standings[names[0]],
                    standings[names[1]],
                    1.0 if winner_name == names[0] else 0.0,
                )
            record = {
                "game": game_no,
                "players": names,
                "scores": match.scores,
                "winner": winner_name if not tie else None,
                "steps": match.steps,
                "duration_s": round(match.duration_s, 2),
            }
            result.games.append(record)
            if on_game:
                on_game(record)
            game_no += 1
            if on_progress is not None:
                on_progress(
                    game_no,
                    total,
                    f"{names[0]} vs {names[1]}: {match.scores[0]}-{match.scores[1]}",
                )
    return result
