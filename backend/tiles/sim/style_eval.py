"""Next-move prediction against opponents with habits outside the model.

Like ``prediction_eval`` but the player being predicted is a style Tactician
(``tiles.agents.tacticians.styles``) instead of a greedy bot with different
weights. It reports how often the Profiler's first and top-three guesses hit,
against a fixed guesser (the default move score) and uniform guessing.
"""

from __future__ import annotations

import random
from typing import Callable, Dict, Optional

from tiles.agents.base import DecisionContext
from tiles.agents.profiler import BasicProfiler
from tiles.agents.tacticians.greedy import GreedyTactician
from tiles.agents.tacticians.heuristics import rank_actions
from tiles.agents.tacticians.styles import make_style_tactician
from tiles.core import deal_round, legal_actions, new_game, step


def evaluate_style_prediction(
    style: str,
    games: int = 20,
    seed: int = 0,
    stop_check: Optional[Callable[[], bool]] = None,
    profiler_factory: Callable[[], object] = BasicProfiler,
) -> Dict[str, float]:
    """Predict a style opponent's moves over ``games`` two-player games."""
    counts = {"n": 0, "profiler_top1": 0, "profiler_top3": 0, "static_top1": 0, "static_top3": 0,
              "uniform_top1": 0.0, "uniform_top3": 0.0}
    for g in range(games):
        if stop_check is not None and stop_check():
            break
        game_seed = seed * 1000 + g
        subject = make_style_tactician(style, seed=game_seed)
        opponent = GreedyTactician()
        profiler = profiler_factory()
        state = new_game(2, seed=game_seed, player_names=["subject", "opponent"])
        rng = random.Random(game_seed)
        tacticians = [subject, opponent]
        while not state.is_game_over:
            mover = state.current_player
            legal = legal_actions(state)
            if mover == 0:
                dist = profiler.predict(state, 0, legal)
                ranked = [aid for aid, _ in sorted(dist.items(), key=lambda kv: kv[1], reverse=True)]
                static = [a.action_id for a, _, _ in rank_actions(state, legal)]
            decision = tacticians[mover].decide(DecisionContext(state=state, player_index=mover, legal=legal))
            if mover == 0:
                actual = decision.action.action_id
                counts["n"] += 1
                counts["profiler_top1"] += int(ranked[0] == actual)
                counts["profiler_top3"] += int(actual in ranked[:3])
                counts["static_top1"] += int(static[0] == actual)
                counts["static_top3"] += int(actual in static[:3])
                counts["uniform_top1"] += 1.0 / len(legal)
                counts["uniform_top3"] += min(3, len(legal)) / len(legal)
            before = state.clone()
            move, round_result = step(state, decision.action)
            profiler.observe(before, decision.action, move)
            if round_result is not None and not round_result.game_over:
                deal_round(state, rng)
    return counts
