"""Ablation study: does opponent profiling actually help?

Isolates the Profiler's contribution by playing the same MCTS Tactician
with and without profiler-predicted opponent policies injected into the
search (the report's headline experiment), against a fixed heuristic
opponent. Metrics land in MLflow when installed, else a JSONL file.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from tiles.sim.match import MatchConfig, MatchRunner
from tiles.telemetry import get_tracker

# The fixed opponent: a denial-heavy greedy "blocker", so there is a
# consistent style for the Profiler to learn and exploit.
BLOCKER_WEIGHTS = {
    "immediate_points": 3.0,
    "line_progress": 1.0,
    "near_completion": 0.8,
    "floor_penalty": 1.0,
    "first_player": 0.7,
    "bonus_potential": 0.4,
    "denial": 2.5,
}


@dataclass
class ConditionResult:
    name: str
    wins: int = 0
    games: int = 0
    margins: List[int] = field(default_factory=list)
    decision_ms: List[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "condition": self.name,
            "games": self.games,
            "wins": self.wins,
            "win_rate": round(self.wins / self.games, 3) if self.games else 0,
            "avg_margin": (
                round(statistics.mean(self.margins), 2) if self.margins else 0
            ),
            "avg_decision_ms": (
                round(statistics.mean(self.decision_ms), 1)
                if self.decision_ms
                else 0
            ),
        }


def _run_condition(
    name: str,
    tactician: str,
    tactician_config: Dict,
    profiler: Optional[str],
    games: int,
    seed: int,
    tracker,
) -> ConditionResult:
    result = ConditionResult(name=name)
    with tracker.run(
        name,
        params={
            "tactician": tactician,
            "profiler": profiler or "none",
            "games": games,
            **tactician_config,
        },
    ):
        for g in range(games):
            # Alternate seats to cancel first-player advantage.
            subject_seat = g % 2
            players = [
                {
                    "name": "blocker",
                    "tactician": "greedy",
                    "config": {"weights": BLOCKER_WEIGHTS},
                }
            ]
            players.insert(
                subject_seat,
                {
                    "name": "subject",
                    "tactician": tactician,
                    "config": dict(tactician_config),
                },
            )
            config = MatchConfig(
                players=players,
                profiler=profiler,
                explainer=None,
                seed=seed + g,
            )
            match = MatchRunner(config, keep_records=True).run()
            subject_score = match.scores[subject_seat]
            blocker_score = match.scores[1 - subject_seat]
            won = match.winner == subject_seat
            result.games += 1
            result.wins += int(won)
            result.margins.append(subject_score - blocker_score)
            for record in match.records or []:
                if record.get("player_name") == "subject":
                    result.decision_ms.append(
                        record.get("timing", {}).get("decide_ms", 0.0)
                    )
            tracker.log_metrics(
                {
                    "win": int(won),
                    "margin": subject_score - blocker_score,
                    "subject_score": subject_score,
                },
                step=g,
            )
        tracker.log_metrics(
            {
                "win_rate": result.wins / max(result.games, 1),
                "avg_margin": (
                    statistics.mean(result.margins) if result.margins else 0
                ),
            }
        )
    return result


def run_ablation(
    games: int = 10,
    simulations: int = 200,
    seed: int = 0,
    tracker_backend: str = "auto",
) -> List[ConditionResult]:
    """Three conditions, most-ablated first:

    1. ``greedy``          — heuristic baseline, no search, no profiling
    2. ``mcts``            — PUCT search, heuristic priors only
    3. ``mcts_profiled``   — PUCT search + Profiler-predicted opponent policy
    """
    tracker = get_tracker(tracker_backend)
    conditions = [
        ("greedy", "greedy", {}, None),
        ("mcts", "mcts", {"simulations": simulations}, "basic"),
        (
            "mcts_profiled",
            "mcts_profiled",
            {"simulations": simulations},
            "basic",
        ),
    ]
    results = []
    for name, tactician, config, profiler in conditions:
        print(f"[ablation] running condition {name!r} ({games} games)...")
        result = _run_condition(
            name, tactician, config, profiler, games, seed, tracker
        )
        print(f"[ablation]   {result.to_dict()}")
        results.append(result)
    return results


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", type=int, default=10)
    parser.add_argument("--simulations", type=int, default=200)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--tracker", default="auto", choices=["auto", "mlflow", "jsonl", "null"]
    )
    args = parser.parse_args()
    results = run_ablation(
        args.games, args.simulations, args.seed, args.tracker
    )
    print("\ncondition        games  win_rate  avg_margin  avg_decide_ms")
    for r in results:
        d = r.to_dict()
        print(
            f"{d['condition']:<16}{d['games']:>6}{d['win_rate']:>10.3f}"
            f"{d['avg_margin']:>12.2f}{d['avg_decision_ms']:>15.1f}"
        )


if __name__ == "__main__":
    main()
