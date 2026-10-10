"""Monte Carlo Tree Search (UCT) over the exact within-round game tree, with optional
profiler conditioning.

Within a round every tile is visible, so the tree is fully known; only opponents' choices are
uncertain. Each iteration selects a path with UCB1 (maximising at my nodes, minimising at
opponents'), expands one child, finishes the round with heuristic playouts, values the position
(banked score + board potential, opponents' share weighted by ``value.opponent``) and backs it up.
Children are limited to the heuristic's best moves (progressive widening) to keep the branching
factor tractable.

Profiler conditioning: with ``conditioned=True`` the player watches every opponent move, keeps an
``OpponentModel`` per opponent, and plays that opponent's inferred style in the tree and the
playouts instead of the generic balanced heuristic. This is the "MCTS with profiler conditioning"
of the proposal; whether it helps is measured in scripts/evaluate_mcts.py.
"""

from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from tiles.azul.game import GameSim, apply_action, round_over, score_round
from tiles.azul.rules import get_legal_actions
from tiles.ml.greedy_player import DEFAULT_WEIGHTS, GreedyPlayer, Weights, _score_action
from tiles.ml.opponent_model import STYLE_LIBRARY, OpponentModel
from tiles.ml.rollout_player import ValueWeights, _sim_from_state, potential
from tiles.models.schemas import GameAction, GameStateData

logger = logging.getLogger(__name__)

VALUE_SCALE = 20.0          # leaf values are divided by this so UCB1's constant is meaningful


@dataclass
class Node:
    action: Optional[GameAction]
    mover: int                              # who plays at THIS node (the player to move)
    parent: Optional[Node] = None
    children: List[Node] = field(default_factory=list)
    untried: Optional[List[GameAction]] = None
    visits: int = 0
    total: float = 0.0                      # sum of leaf values from the root player's perspective

    @property
    def mean(self) -> float:
        return self.total / self.visits if self.visits else 0.0


class MCTSPlayer(GreedyPlayer):
    _name = "MCTSPlayer"

    def __init__(self, iterations: int = 250, time_budget_s: float = 3.0, c: float = 1.1, beam: int = 6,
                 epsilon: float = 0.05, conditioned: bool = False, seed: Optional[int] = None,
                 value: Optional[ValueWeights] = None, weights: Optional[Weights] = None,
                 min_observed: int = 6, min_confidence: float = 0.5):
        super().__init__(weights=weights or DEFAULT_WEIGHTS)
        self.iterations = iterations
        self.time_budget_s = time_budget_s
        self.c = c
        self.beam = beam
        self.epsilon = epsilon
        self.conditioned = conditioned
        self.value = value or ValueWeights(opponent=0.4)
        self.min_observed = min_observed
        self.min_confidence = min_confidence
        self._rng = random.Random(seed)
        self._models: Dict[str, OpponentModel] = {}
        self._opp_weights: Dict[str, Weights] = {}
        self._inferred: Dict[str, dict] = {}

    # -- profiler conditioning ------------------------------------------------------
    def observe(self, record: dict, observer_name: str) -> None:
        """Called with every move; feeds the per-opponent style models when conditioned."""
        if not self.conditioned or record["player_name"] == observer_name:
            return
        from tiles.ml.archetypes import state_from_record  # local import: avoids a hard dependency cycle

        state = state_from_record(record)
        if state is None:
            return
        name = record["player_name"]
        idx = next((i for i, p in enumerate(state.players) if p.name == name), None)
        if idx is None:
            return
        from tiles.models.schemas import DestinationType, SourceType, TileColor

        a = record["action"]
        action = GameAction(source_type=SourceType(a["source_type"]), source_index=a["source_index"],
                            color=TileColor(a["color"]), destination=DestinationType(a["destination"]),
                            destination_row=a["destination_row"])
        self._models.setdefault(name, OpponentModel()).observe(state, idx, action)

    def _refresh_opponents(self) -> None:
        self._opp_weights, self._inferred = {}, {}
        for name, model in self._models.items():
            if model.observed < self.min_observed:
                continue
            style, p = model.likely_style()
            if p >= self.min_confidence:
                self._opp_weights[name] = STYLE_LIBRARY[style]
                self._inferred[name] = {"style": style, "confidence": round(p, 3), "moves_observed": model.observed}

    # -- search ---------------------------------------------------------------------
    def _weights_for(self, names: List[str], idx: int, me: int) -> Weights:
        return self.weights if idx == me else self._opp_weights.get(names[idx], self.weights)

    def _ranked(self, sim: GameSim, w: Weights) -> List[GameAction]:
        player = sim.state.players[sim.current]
        legal = get_legal_actions(sim.state, sim.current)
        ranked = sorted(legal, key=lambda a: _score_action(sim.state, player, a, w), reverse=True)
        top = ranked[: self.beam]
        floor = next((a for a in ranked if a.destination.value == "floor"), None)
        if floor is not None and floor not in top:
            top.append(floor)
        return top

    def _playout(self, sim: GameSim, me: int, names: List[str]) -> float:
        guard = 0
        while not round_over(sim.state) and guard < 80:
            idx = sim.current
            w = self._weights_for(names, idx, me)
            legal = get_legal_actions(sim.state, idx)
            if self.epsilon and self._rng.random() < self.epsilon:
                action = self._rng.choice(legal)
            else:
                player = sim.state.players[idx]
                action = max(legal, key=lambda a: _score_action(sim.state, player, a, w))
            apply_action(sim, action)
            guard += 1
        had = sim.state.players[me].has_first_player_token
        score_round(sim)
        sim.state.players[me].has_first_player_token = had
        s = sim.state
        mine = s.players[me]
        others = [p for i, p in enumerate(s.players) if i != me]
        my = mine.score + potential(mine, self.value) + (self.value.token if had else 0)
        theirs = sum(p.score + potential(p, self.value) for p in others) / max(1, len(others))
        return (my - self.value.opponent * theirs) / VALUE_SCALE

    def _select_child(self, node: Node, me: int) -> Node:
        log_n = math.log(max(1, node.visits))
        sign = 1.0 if node.mover == me else -1.0
        return max(node.children, key=lambda ch: sign * ch.mean + self.c * math.sqrt(log_n / max(1, ch.visits)))

    def _search(self, root_sim: GameSim, me: int, names: List[str]) -> Node:
        root = Node(None, root_sim.current)
        root.untried = self._ranked(root_sim, self.weights)
        deadline = time.monotonic() + self.time_budget_s
        for it in range(self.iterations):
            if it >= 2 and time.monotonic() > deadline:
                break
            sim = root_sim.copy()
            node = root
            # selection
            while node.untried == [] and node.children and not round_over(sim.state):
                node = self._select_child(node, me)
                apply_action(sim, node.action)
            # expansion
            if node.untried and not round_over(sim.state):
                action = node.untried.pop(0)                     # best-first (heuristic order)
                apply_action(sim, action)
                child = Node(action, sim.current, parent=node)
                if not round_over(sim.state):
                    child.untried = self._ranked(sim, self._weights_for(names, sim.current, me))
                else:
                    child.untried = []
                node.children.append(child)
                node = child
            # simulation + backup
            value = self._playout(sim, me, names)
            while node is not None:
                node.visits += 1
                node.total += value
                node = node.parent
        return root

    async def decide(self, game_state: GameStateData, player_index: int) -> GameAction:
        legal = get_legal_actions(game_state, player_index)
        if not legal:
            raise ValueError("No legal actions available")
        if self.conditioned:
            self._refresh_opponents()
        names = [p.name for p in game_state.players]
        root_sim = _sim_from_state(game_state, player_index, self._rng)
        root = self._search(root_sim, player_index, names)
        ranked = sorted(root.children, key=lambda ch: ch.visits, reverse=True)
        best = ranked[0]
        self.last_explanation = {
            "model": self.name, "chosen_score": round(best.mean * VALUE_SCALE, 2), "n_legal": len(legal),
            "method": f"UCT {root.visits} iterations, beam {self.beam}" + (", profiler-conditioned" if self.conditioned else ""),
            "top_alternatives": [
                {"action": ch.action.model_dump(), "score": round(ch.mean * VALUE_SCALE, 2), "visits": ch.visits}
                for ch in ranked[:3]
            ],
        }
        if self.conditioned:
            self.last_explanation["adaptation"] = {
                "opponents": self._inferred, "playing_as": "mcts",
                "reason": ("simulating opponents as: " + ", ".join(f"{n} ~ {e['style']}" for n, e in self._inferred.items()))
                if self._inferred else "not enough confident opponent evidence; simulating balanced opponents",
            }
        logger.info(f"[{self.name}] {best.action.color.value} {best.action.source_type.value}[{best.action.source_index}] "
                    f"-> {best.action.destination.value}[{best.action.destination_row}] visits={best.visits}/{root.visits}")
        return best.action


class ConditionedMCTSPlayer(MCTSPlayer):
    """MCTS whose simulated opponents follow their inferred play style."""

    _name = "ConditionedMCTSPlayer"

    def __init__(self, **kw):
        kw.setdefault("conditioned", True)
        super().__init__(**kw)
