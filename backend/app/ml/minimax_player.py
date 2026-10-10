"""Minimax baseline: depth-limited alpha-beta over the exact within-round game tree.

Within a round every tile is visible, so the tree below the current position is fully known;
only the opponents' (unknowable) choices make it adversarial. Moves are searched in order of the
greedy heuristic and limited to a beam (``beam`` best moves per ply, plus the best floor dump) to
keep the branching factor tractable. At the depth limit the position is finished with greedy play
to the end of the round and valued by ``my score + potential - opponents' score + potential``.
With more than two players all opponents are treated as one minimising side ("paranoid" search).

This is the classical-search baseline for the comparison in the proposal; it assumes opponents
play adversarially, whereas ``RolloutPlayer`` assumes they play like the heuristic.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional, Tuple

from app.azul.game import GameSim, apply_action, round_over, score_round
from app.azul.rules import get_legal_actions
from app.ml.greedy_player import DEFAULT_WEIGHTS, GreedyPlayer, Weights, _score_action
from app.ml.rollout_player import DEFAULT_VALUE, ValueWeights, _sim_from_state, potential
from app.models.schemas import GameAction, GameStateData

logger = logging.getLogger(__name__)


class MinimaxPlayer(GreedyPlayer):
    _name = "MinimaxPlayer"

    def __init__(self, depth: int = 3, beam: int = 5, time_budget_s: float = 4.0,
                 value: Optional[ValueWeights] = None, weights: Optional[Weights] = None,
                 seed: Optional[int] = None):
        super().__init__(weights=weights or DEFAULT_WEIGHTS)
        self.depth = depth
        self.beam = beam
        self.time_budget_s = time_budget_s
        # opponent weight 0.4, not the classical zero-sum 1.0: measured to beat the 1.0 setting in
        # mirror play (55 vs 31 points each) while still beating Greedy and Rollout players
        self.value = value or ValueWeights(opponent=0.4)
        self.nodes = 0
        self._deadline = 0.0

    # -- evaluation ---------------------------------------------------------------
    def _leaf(self, sim: GameSim, me: int) -> float:
        guard = 0
        while not round_over(sim.state) and guard < 80:
            apply_action(sim, self._best(sim)[0][0][0])
            guard += 1
        had = sim.state.players[me].has_first_player_token
        score_round(sim)
        sim.state.players[me].has_first_player_token = had
        s = sim.state
        mine = s.players[me]
        others = [p for i, p in enumerate(s.players) if i != me]
        my = mine.score + potential(mine, self.value) + (self.value.token if had else 0)
        theirs = sum(p.score + potential(p, self.value) for p in others) / max(1, len(others))
        return my - self.value.opponent * theirs

    def _best(self, sim: GameSim) -> Tuple[List[Tuple[GameAction, float]], int]:
        """Legal moves of the player to move, best first by the greedy heuristic."""
        idx = sim.current
        player = sim.state.players[idx]
        ranked = sorted(((a, _score_action(sim.state, player, a, self.weights))
                         for a in get_legal_actions(sim.state, idx)), key=lambda x: x[1], reverse=True)
        return ranked, idx

    def _candidates(self, sim: GameSim) -> List[GameAction]:
        ranked, _ = self._best(sim)
        top = [a for a, _ in ranked[: self.beam]]
        floor = next((a for a, _ in ranked if a.destination.value == "floor"), None)
        if floor is not None and floor not in top:
            top.append(floor)
        return top

    # -- search -------------------------------------------------------------------
    def _search(self, sim: GameSim, depth: int, alpha: float, beta: float, me: int) -> float:
        self.nodes += 1
        if round_over(sim.state):
            return self._leaf(sim, me)
        if depth == 0 or time.monotonic() > self._deadline:
            return self._leaf(sim.copy(), me)
        maximizing = sim.current == me
        best = float("-inf") if maximizing else float("inf")
        for action in self._candidates(sim):
            child = sim.copy()
            apply_action(child, action)
            v = self._search(child, depth - 1, alpha, beta, me)
            if maximizing:
                best = max(best, v)
                alpha = max(alpha, best)
            else:
                best = min(best, v)
                beta = min(beta, best)
            if beta <= alpha:
                break
        return best

    async def decide(self, game_state: GameStateData, player_index: int) -> GameAction:
        legal = get_legal_actions(game_state, player_index)
        if not legal:
            raise ValueError("No legal actions available")
        root = _sim_from_state(game_state, player_index, __import__("random").Random(0))
        self.nodes = 0
        self._deadline = time.monotonic() + self.time_budget_s
        results: List[Tuple[GameAction, float]] = []
        alpha = float("-inf")
        for action in self._candidates(root):
            child = root.copy()
            apply_action(child, action)
            v = self._search(child, self.depth - 1, alpha, float("inf"), player_index)
            results.append((action, v))
            alpha = max(alpha, v)
        results.sort(key=lambda x: x[1], reverse=True)
        best, value = results[0]
        self.last_explanation = {
            "model": self.name, "chosen_score": round(value, 2), "n_legal": len(legal),
            "method": f"alpha-beta depth {self.depth}, beam {self.beam}, {self.nodes} nodes",
            "top_alternatives": [{"action": a.model_dump(), "score": round(v, 2)} for a, v in results[:3]],
        }
        logger.info(f"[{self.name}] {best.color.value} {best.source_type.value}[{best.source_index}] -> "
                    f"{best.destination.value}[{best.destination_row}] value={value:.1f} nodes={self.nodes}")
        return best


class ConditionedMinimaxPlayer(MinimaxPlayer):
    """Minimax whose opponent nodes consider the moves that opponent's inferred play style prefers.

    The adversarial search still allows every candidate reply, but the beam at an opponent's node is
    chosen with that opponent's inferred heuristic weights instead of the generic ones, so the
    replies actually examined are the ones that style is likely to play (profiler conditioning).
    """

    _name = "ConditionedMinimaxPlayer"

    def __init__(self, min_observed: int = 6, min_confidence: float = 0.5, **kw):
        super().__init__(**kw)
        self.min_observed = min_observed
        self.min_confidence = min_confidence
        self._models: dict = {}
        self._opp_weights: dict = {}
        self._inferred: dict = {}
        self._names: List[str] = []

    def observe(self, record: dict, observer_name: str) -> None:
        if record["player_name"] == observer_name:
            return
        from app.ml.archetypes import state_from_record
        from app.ml.opponent_model import OpponentModel
        from app.models.schemas import DestinationType, SourceType, TileColor

        state = state_from_record(record)
        if state is None:
            return
        idx = next((i for i, p in enumerate(state.players) if p.name == record["player_name"]), None)
        if idx is None:
            return
        a = record["action"]
        action = GameAction(source_type=SourceType(a["source_type"]), source_index=a["source_index"],
                            color=TileColor(a["color"]), destination=DestinationType(a["destination"]),
                            destination_row=a["destination_row"])
        self._models.setdefault(record["player_name"], OpponentModel()).observe(state, idx, action)

    def _candidates(self, sim: GameSim) -> List[GameAction]:
        name = self._names[sim.current] if sim.current < len(self._names) else None
        w = self._opp_weights.get(name, self.weights)
        idx = sim.current
        player = sim.state.players[idx]
        ranked = sorted(get_legal_actions(sim.state, idx), key=lambda a: _score_action(sim.state, player, a, w),
                        reverse=True)
        top = ranked[: self.beam]
        floor = next((a for a in ranked if a.destination.value == "floor"), None)
        if floor is not None and floor not in top:
            top.append(floor)
        return top

    async def decide(self, game_state: GameStateData, player_index: int) -> GameAction:
        from app.ml.opponent_model import STYLE_LIBRARY

        self._names = [p.name for p in game_state.players]
        self._opp_weights, self._inferred = {}, {}
        for name, model in self._models.items():
            if model.observed >= self.min_observed:
                style, p = model.likely_style()
                if p >= self.min_confidence:
                    self._opp_weights[name] = STYLE_LIBRARY[style]
                    self._inferred[name] = {"style": style, "confidence": round(p, 3), "moves_observed": model.observed}
        action = await super().decide(game_state, player_index)
        self.last_explanation["adaptation"] = {
            "opponents": self._inferred, "playing_as": "minimax",
            "reason": ("searching replies as: " + ", ".join(f"{n} ~ {e['style']}" for n, e in self._inferred.items()))
            if self._inferred else "not enough confident opponent evidence; generic reply ordering",
        }
        return action
