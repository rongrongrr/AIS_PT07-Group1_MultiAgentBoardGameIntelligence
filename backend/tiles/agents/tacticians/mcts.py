"""Monte Carlo Tree Search Tactician (PUCT), optionally opponent-aware.

Perspective convention
----------------------
All edge values (W/N, i.e. Q) are stored from the ROOT player's
perspective in [-1, 1]. During selection the player to move at a node
picks the edge maximizing ``sign * Q + U`` where ``sign`` is +1 for the
root player and -1 for opponents (paranoid reduction: opponents are
assumed to minimize the root player's value).

Priors are a softmax over the shared heuristic action scores. When
``use_opponent_model`` is on and the orchestrator injected
``ctx.opponent_policy``, priors at opponent nodes are blended
``0.7 * predicted + 0.3 * heuristic`` — this is how the Profiler's
behavioral prediction steers the search toward futures the *actual*
opponent is likely to choose.

Chance handling
---------------
The redeal between rounds is stochastic, so the tree never grows past a
round boundary. A child whose creation resolved the round (game not
over) is a *chance leaf*: every visit clones it, samples a fresh deal
from the per-decision RNG, and rolls out — i.e. each simulation
determinizes its own deal.

Rollouts are epsilon-greedy over the heuristic (argmax of a sampled
subset of legal actions, for speed) for at most two further round
resolutions, then bootstrapped with ``tanh(evaluate_state / 20)``.
"""

from __future__ import annotations

import math
import random
import time
from typing import Callable, Dict, List, Optional

from tiles.agents.base import (
    CandidateMove,
    Decision,
    DecisionContext,
    SearchReport,
    Tactician,
)
from tiles.core import Action, GameState, deal_round, legal_actions, step

from .heuristics import evaluate_state, score_action

_ROLLOUT_SAMPLE = 6  # actions scored per rollout step
_ROLLOUT_EPSILON = 0.2  # probability of a uniform-random rollout move
_ROLLOUT_ROUNDS = 2  # further round resolutions before bootstrapping
_PRIOR_TEMPERATURE = 2.0
_OPPONENT_BLEND = 0.7  # weight on the Profiler's predicted distribution


def _softmax(scores: List[float], temperature: float) -> List[float]:
    top = max(scores)
    exps = [math.exp((s - top) / temperature) for s in scores]
    total = sum(exps)
    return [e / total for e in exps]


class _Node:
    """One materialized tree node (state is post-action, pre-selection)."""

    __slots__ = (
        "state",
        "player",
        "terminal",
        "needs_deal",
        "actions",
        "priors",
        "edge_n",
        "edge_w",
        "children",
        "visits",
    )

    def __init__(self, state: GameState, terminal: bool, needs_deal: bool):
        self.state = state
        self.player = state.current_player
        self.terminal = terminal
        self.needs_deal = needs_deal
        self.actions: List[Action] = []
        self.priors: List[float] = []
        self.edge_n: List[int] = []
        self.edge_w: List[float] = []
        self.children: List[Optional["_Node"]] = []
        self.visits = 0


class MCTSTactician(Tactician):
    name = "mcts"

    def __init__(
        self,
        simulations: int = 300,
        c_puct: float = 1.5,
        time_budget_ms: Optional[float] = None,
        use_opponent_model: bool = False,
    ) -> None:
        self.simulations = simulations
        self.c_puct = c_puct
        self.time_budget_ms = time_budget_ms
        self.use_opponent_model = use_opponent_model
        self.uses_opponent_model = use_opponent_model

    # -- node construction ------------------------------------------------

    def _init_edges(
        self,
        node: _Node,
        root_player: int,
        opponent_policy: Optional[Callable],
    ) -> bool:
        """Compute legal actions and priors. Returns True if the
        opponent model contributed to this node's priors."""
        node.actions = legal_actions(node.state)
        scores = [
            score_action(node.state, a)[0] for a in node.actions
        ]
        priors = _softmax(scores, _PRIOR_TEMPERATURE)

        used_model = False
        if (
            self.use_opponent_model
            and opponent_policy is not None
            and node.player != root_player
        ):
            predicted: Dict[int, float] = opponent_policy(
                node.state, node.player, node.actions
            )
            if predicted:
                blended = []
                for action, heuristic_prior in zip(node.actions, priors):
                    p = predicted.get(action.action_id, 0.0)
                    blended.append(
                        _OPPONENT_BLEND * p
                        + (1 - _OPPONENT_BLEND) * heuristic_prior
                    )
                total = sum(blended)
                if total > 0:
                    priors = [b / total for b in blended]
                    used_model = True

        node.priors = priors
        node.edge_n = [0] * len(node.actions)
        node.edge_w = [0.0] * len(node.actions)
        node.children = [None] * len(node.actions)
        return used_model

    def _make_child(self, parent: _Node, edge: int) -> _Node:
        state = parent.state.clone()
        _, round_result = step(state, parent.actions[edge])
        terminal = state.is_game_over
        needs_deal = round_result is not None and not terminal
        return _Node(state, terminal, needs_deal)

    # -- evaluation ---------------------------------------------------------

    @staticmethod
    def _terminal_value(state: GameState, root_player: int) -> float:
        scores = state.scores()
        mine = scores[root_player]
        best_other = max(
            s for i, s in enumerate(scores) if i != root_player
        )
        if mine > best_other:
            return 1.0
        if mine < best_other:
            return -1.0
        return 0.0  # exact score tie (wall tiebreak ignored here)

    def _rollout(
        self, state: GameState, root_player: int, rng: random.Random
    ) -> float:
        """Epsilon-greedy playout for at most _ROLLOUT_ROUNDS round
        resolutions; ``state`` is mutated (pass a clone)."""
        rounds_resolved = 0
        while not state.is_game_over and rounds_resolved < _ROLLOUT_ROUNDS:
            legal = legal_actions(state)
            if not legal:  # pre-deal state handed in
                deal_round(state, rng)
                continue
            if rng.random() < _ROLLOUT_EPSILON:
                action = legal[rng.randrange(len(legal))]
            else:
                sample = (
                    legal
                    if len(legal) <= _ROLLOUT_SAMPLE
                    else rng.sample(legal, _ROLLOUT_SAMPLE)
                )
                action = max(sample, key=lambda a: score_action(state, a)[0])
            _, round_result = step(state, action)
            if round_result is not None:
                rounds_resolved += 1
                if not state.is_game_over:
                    deal_round(state, rng)
        if state.is_game_over:
            return self._terminal_value(state, root_player)
        return math.tanh(evaluate_state(state, root_player) / 20.0)

    def _evaluate_leaf(
        self, node: _Node, root_player: int, rng: random.Random
    ) -> float:
        if node.terminal:
            return self._terminal_value(node.state, root_player)
        state = node.state.clone()
        if node.needs_deal:
            deal_round(state, rng)  # fresh determinization per visit
        return self._rollout(state, root_player, rng)

    # -- selection ------------------------------------------------------------

    def _select_edge(self, node: _Node, root_player: int) -> int:
        sign = 1.0 if node.player == root_player else -1.0
        sqrt_visits = math.sqrt(node.visits + 1)
        best_edge, best_score = 0, -float("inf")
        for i in range(len(node.actions)):
            n = node.edge_n[i]
            q = node.edge_w[i] / n if n else 0.0
            u = self.c_puct * node.priors[i] * sqrt_visits / (1 + n)
            s = sign * q + u
            if s > best_score:
                best_score, best_edge = s, i
        return best_edge

    # -- Tactician interface ----------------------------------------------------

    def decide(self, ctx: DecisionContext) -> Decision:
        start = time.perf_counter()
        rng = random.Random(ctx.rng_seed)
        root_player = ctx.player_index

        root = _Node(ctx.state.clone(), terminal=False, needs_deal=False)
        used_model = self._init_edges(root, root_player, ctx.opponent_policy)

        budget_ms = self.time_budget_ms or ctx.time_budget_ms
        simulations_run = 0
        for _ in range(self.simulations):
            if (
                budget_ms is not None
                and (time.perf_counter() - start) * 1000 >= budget_ms
                and simulations_run > 0
            ):
                break
            node = root
            path: List[tuple] = []
            # Selection: descend until we hit an unmaterialized edge or a leaf.
            while True:
                if node.terminal or node.needs_deal:
                    value = self._evaluate_leaf(node, root_player, rng)
                    break
                edge = self._select_edge(node, root_player)
                path.append((node, edge))
                child = node.children[edge]
                if child is None:
                    child = self._make_child(node, edge)
                    node.children[edge] = child
                    if not (child.terminal or child.needs_deal):
                        used_model |= self._init_edges(
                            child, root_player, ctx.opponent_policy
                        )
                    value = self._evaluate_leaf(child, root_player, rng)
                    child.visits += 1
                    break
                node = child
            # Backpropagation (values already root-perspective).
            for parent, edge in path:
                parent.visits += 1
                parent.edge_n[edge] += 1
                parent.edge_w[edge] += value
            simulations_run += 1

        # Build the report: root edges by visit count.
        order = sorted(
            range(len(root.actions)),
            key=lambda i: (root.edge_n[i], root.priors[i]),
            reverse=True,
        )
        candidates = []
        for i in order[:8]:
            n = root.edge_n[i]
            # The heuristic decomposition of the candidate is a genuine
            # search artifact (it is what the prior was computed from), so
            # the Explainer can state a primary driver and the XAI audit
            # can check it against this breakdown.
            _, components = score_action(ctx.state, root.actions[i])
            notes = {k: float(v) for k, v in components.items()}
            notes["visit_share"] = n / simulations_run if simulations_run else 0.0
            candidates.append(
                CandidateMove(
                    action=root.actions[i],
                    score=root.edge_w[i] / n if n else 0.0,
                    visits=n,
                    prior=root.priors[i],
                    principal_variation=self._principal_variation(root, i),
                    notes=notes,
                )
            )
        report = SearchReport(
            candidates=candidates,
            simulations=simulations_run,
            elapsed_ms=(time.perf_counter() - start) * 1000,
            used_opponent_model=used_model,
            notes={
                "strategy": "PUCT MCTS with determinized redeals",
                "c_puct": self.c_puct,
                "opponent_model_enabled": self.use_opponent_model,
            },
        )
        return Decision(action=candidates[0].action, report=report)

    @staticmethod
    def _principal_variation(root: _Node, first_edge: int) -> List[Action]:
        pv = [root.actions[first_edge]]
        node = root.children[first_edge]
        while (
            node is not None
            and not node.terminal
            and not node.needs_deal
            and node.actions
            and len(pv) < 4
        ):
            if not node.edge_n or max(node.edge_n) == 0:
                break
            edge = max(range(len(node.actions)), key=lambda i: node.edge_n[i])
            pv.append(node.actions[edge])
            node = node.children[edge]
        return pv
