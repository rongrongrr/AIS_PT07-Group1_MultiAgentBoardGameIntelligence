"""Opponent-model evaluation harness.

Measures the report's Opponent Modeling deliverable: next-move
prediction accuracy of the Profiler against two baselines —

* **uniform**  — expected accuracy of guessing uniformly over legal
  moves (computed exactly, not sampled), and
* **static greedy** — always predict the argmax of the population-prior
  heuristic (``DEFAULT_WEIGHTS``), i.e. a non-adaptive opponent model.

The subject players are Greedy tacticians with *distinct* weight
presets (a denial-heavy "blocker" and a bonus-heavy "collector"), so
the profiler has real behavioral signal to pick up within a game.

Predictions are additionally bucketed by game phase (early = rounds
1–2, mid = 3–4, late = 5+) to show the cold-start prior→posterior
transition: the profiler should pull away from the static baseline as
the game goes on.

Run directly:  python -m tiles.sim.prediction_eval [games] [seed]
"""

from __future__ import annotations

import random
from typing import Callable, Dict, List, Optional

from tiles.agents.base import DecisionContext
from tiles.agents.profiler import BasicProfiler
from tiles.agents.tacticians.greedy import GreedyTactician
from tiles.agents.tacticians.heuristics import DEFAULT_WEIGHTS, rank_actions
from tiles.core import deal_round, legal_actions, new_game, step

PHASES = ("early", "mid", "late")


def _scaled(base: Dict[str, float], **scales: float) -> Dict[str, float]:
    weights = dict(base)
    for key, factor in scales.items():
        weights[key] = weights[key] * factor
    return weights


#: Denial-heavy: plays the opponent, tolerates floor pain.
BLOCKER_WEIGHTS = _scaled(
    DEFAULT_WEIGHTS,
    denial=6.0,
    immediate_points=0.6,
    bonus_potential=0.4,
    floor_penalty=0.5,
    first_player=2.0,
)

#: Bonus-heavy: chases color sets/columns over immediate points.
COLLECTOR_WEIGHTS = _scaled(
    DEFAULT_WEIGHTS,
    bonus_potential=6.0,
    near_completion=2.0,
    immediate_points=0.7,
    denial=0.3,
)

SUBJECT_PRESETS = [
    ("blocker", BLOCKER_WEIGHTS),
    ("collector", COLLECTOR_WEIGHTS),
]


def phase_of(round_number: int) -> str:
    if round_number <= 2:
        return "early"
    if round_number <= 4:
        return "mid"
    return "late"


def _new_counters() -> Dict[str, float]:
    return {
        "predictor_top1": 0,
        "predictor_top3": 0,
        "greedy_top1": 0,
        "greedy_top3": 0,
        "uniform_top1": 0.0,
        "uniform_top3": 0.0,
        "n": 0,
    }


def _rates(counters: Dict[str, float]) -> dict:
    n = counters["n"]

    def rate(count) -> float:
        return count / n if n else 0.0

    return {
        "n": int(n),
        "predictor": {
            "top1": rate(counters["predictor_top1"]),
            "top3": rate(counters["predictor_top3"]),
        },
        "static_greedy": {
            "top1": rate(counters["greedy_top1"]),
            "top3": rate(counters["greedy_top3"]),
        },
        "uniform": {
            "top1": rate(counters["uniform_top1"]),
            "top3": rate(counters["uniform_top3"]),
        },
    }


def evaluate_prediction_accuracy(
    games: int = 20,
    seed: int = 0,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    stop_check: Optional[Callable[[], bool]] = None,
) -> dict:
    """Play ``games`` 2-player games; before every subject move, score
    each predictor's guess against the move actually taken."""
    overall = _new_counters()
    by_phase: Dict[str, Dict[str, float]] = {p: _new_counters() for p in PHASES}
    archetypes: List[dict] = []
    games_played = 0

    for game_index in range(games):
        if stop_check is not None and stop_check():
            break
        preset_name, preset = SUBJECT_PRESETS[game_index % len(SUBJECT_PRESETS)]
        subject = GreedyTactician(preset)
        opponent = GreedyTactician(DEFAULT_WEIGHTS)
        tacticians = [subject, opponent]
        profiler = BasicProfiler()  # fresh: measures within-game learning

        game_seed = seed * 1000 + game_index
        state = new_game(
            2, seed=game_seed, player_names=[f"subject_{preset_name}", "opponent"]
        )
        rng = random.Random(game_seed)

        while not state.is_game_over:
            mover = state.current_player
            legal = legal_actions(state)

            if mover == 0:  # subject: predict before observing
                dist = profiler.predict(state, 0, legal)
                ranked_ids = [
                    aid
                    for aid, _ in sorted(
                        dist.items(), key=lambda item: item[1], reverse=True
                    )
                ]
                greedy_ranked = [
                    a.action_id for a, _, _ in rank_actions(state, legal)
                ]

                decision = tacticians[mover].decide(
                    DecisionContext(state=state, player_index=mover, legal=legal)
                )
                actual = decision.action.action_id

                for bucket in (overall, by_phase[phase_of(state.round_number)]):
                    bucket["predictor_top1"] += int(ranked_ids[0] == actual)
                    bucket["predictor_top3"] += int(actual in ranked_ids[:3])
                    bucket["greedy_top1"] += int(greedy_ranked[0] == actual)
                    bucket["greedy_top3"] += int(actual in greedy_ranked[:3])
                    bucket["uniform_top1"] += 1.0 / len(legal)
                    bucket["uniform_top3"] += min(3, len(legal)) / len(legal)
                    bucket["n"] += 1
            else:
                decision = tacticians[mover].decide(
                    DecisionContext(state=state, player_index=mover, legal=legal)
                )

            state_before = state.clone()
            move, round_result = step(state, decision.action)
            profiler.observe(state_before, decision.action, move)
            if round_result is not None and not round_result.game_over:
                deal_round(state, rng)

        profile = profiler.profile(0)
        archetypes.append(
            {
                "game": game_index,
                "preset": preset_name,
                "archetype": profile.archetype,
                "confidence": round(profile.confidence, 3),
                "moves_observed": profile.moves_observed,
            }
        )
        games_played += 1
        if on_progress is not None:
            on_progress(
                games_played,
                games,
                f"game {games_played}/{games} ({preset_name}) -> {profile.archetype}",
            )

    rates = _rates(overall)
    return {
        "games": games_played,
        "n_predictions": rates["n"],
        "predictor": rates["predictor"],
        "static_greedy": rates["static_greedy"],
        "uniform": rates["uniform"],
        "by_phase": {phase: _rates(counters) for phase, counters in by_phase.items()},
        "archetypes": archetypes,
    }


def main() -> None:
    import sys

    games = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    results = evaluate_prediction_accuracy(games=games, seed=seed)

    print(f"games={results['games']}  predictions={results['n_predictions']}")
    for model in ("predictor", "static_greedy", "uniform"):
        stats = results[model]
        print(
            f"{model:>14}:  top-1 {stats['top1']:.1%}   top-3 {stats['top3']:.1%}"
        )
    print("by phase (predictor top-1):")
    for phase in PHASES:
        stats = results["by_phase"][phase]
        print(
            f"  {phase:>6}: top-1 {stats['predictor']['top1']:.1%} "
            f"(static greedy {stats['static_greedy']['top1']:.1%}, n={stats['n']})"
        )
    print("archetype classifications of the subject player:")
    for row in results["archetypes"]:
        print(
            f"  game {row['game']:>2} ({row['preset']:>9}): "
            f"{row['archetype']} ({row['confidence']:.0%}, "
            f"{row['moves_observed']} moves)"
        )


if __name__ == "__main__":
    main()
