"""Lookahead player: picks the move whose simulated end-of-round position is best.

For each of the heuristic's top candidate moves it plays out the rest of the round on a
copy of the board (everyone choosing by the greedy heuristic, with some randomness), applies
wall tiling and floor penalties, and values the result as
``my score + board potential - average opponent score - their potential``.

Within a round all tiles are visible, so this is exact apart from opponent choices; the
hidden bag only matters for the next deal and is not needed. Where GreedyPlayer only
reasons about the current move, this sees consequences such as what it leaves for the
opponent, whether lines can still be completed before the round ends, and floor spill.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from app.azul.game import GameSim, apply_action, floor_size, round_over, score_round
from app.azul.rules import get_legal_actions, wall_column_for_color
from app.ml.greedy_player import DEFAULT_WEIGHTS, GreedyPlayer, Weights, _score_action
from app.models.schemas import GameAction, GameStateData, PlayerState, TileColor

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ValueWeights:
    """How the leaf position is valued beyond the score already banked."""

    line_progress: float = 1.2   # per-row credit for an unfinished pattern line (scaled by fill)
    row: float = 0.25            # wall rows/columns/colours: credit grows with the square of tiles held
    column: float = 0.6
    color: float = 0.8
    token: float = 0.5           # holding the first-player token (acts first next round)
    opponent: float = 0.4        # how much an opponent's points/potential count against me (1.0 = pure margin, which makes mirror matches destructive)


DEFAULT_VALUE = ValueWeights()


def potential(player: PlayerState, w: ValueWeights = DEFAULT_VALUE) -> float:
    """Heuristic worth of a board beyond its score: progress towards bonuses and lines."""
    v = 0.0
    for r in range(5):
        filled = len(player.pattern_lines[r])
        if 0 < filled < r + 1:
            v += w.line_progress * (filled / (r + 1)) * (r + 1) ** 0.5
    for r in range(5):
        v += w.row * sum(player.wall[r]) ** 2
    for c in range(5):
        v += w.column * sum(player.wall[r][c] for r in range(5)) ** 2
    for color in TileColor.all_colors():
        v += w.color * sum(player.wall[r][wall_column_for_color(r, color)] for r in range(5)) ** 2
    return v


def _sim_from_state(state: GameStateData, current: int, rng: random.Random) -> GameSim:
    return GameSim(state=state.model_copy(deep=True), bag=[], lid=[], rng=rng, current=current)


def _pick(sim: GameSim, weights: Weights, rng: random.Random, epsilon: float) -> GameAction:
    """Heuristic move for whoever is to play in ``sim``; epsilon adds exploration."""
    idx = sim.current
    legal = get_legal_actions(sim.state, idx)
    if epsilon and rng.random() < epsilon:
        return rng.choice(legal)
    player = sim.state.players[idx]
    return max(legal, key=lambda a: _score_action(sim.state, player, a, weights))


class RolloutPlayer(GreedyPlayer):
    """Greedy shortlist + round-end rollouts."""

    _name = "RolloutPlayer"

    def __init__(self, candidates: int = 8, rollouts: int = 3, epsilon: float = 0.12,
                 seed: Optional[int] = None, time_budget_s: float = 4.0,
                 value: ValueWeights = DEFAULT_VALUE, weights: Optional[Weights] = None):
        super().__init__(weights=weights or DEFAULT_WEIGHTS)
        self.candidates = candidates
        self.rollouts = rollouts
        self.epsilon = epsilon
        self.time_budget_s = time_budget_s
        self.value = value
        self._rng = random.Random(seed)

    def opponent_weights(self, state: GameStateData) -> Dict[str, Weights]:
        """Heuristic weights to simulate each opponent with (by name); default = balanced.
        Subclasses override this to plug in an opponent model."""
        return {}

    # -- evaluation ---------------------------------------------------------------
    def _leaf_value(self, sim: GameSim, me: int) -> float:
        s = sim.state
        mine = s.players[me]
        others = [p for i, p in enumerate(s.players) if i != me]
        my = mine.score + potential(mine, self.value) + (self.value.token if mine.has_first_player_token else 0)
        theirs = sum(p.score + potential(p, self.value) for p in others) / max(1, len(others))
        return my - self.value.opponent * theirs

    def _rollout(self, state: GameStateData, me: int, first: GameAction, explore: bool,
                 opp: Optional[Dict[str, Weights]] = None) -> float:
        sim = _sim_from_state(state, me, self._rng)
        apply_action(sim, first)
        eps = self.epsilon if explore else 0.0
        guard = 0
        opp = opp or {}
        names = [p.name for p in sim.state.players]
        while not round_over(sim.state) and guard < 80:
            w = self.weights if sim.current == me else opp.get(names[sim.current], self.weights)
            apply_action(sim, _pick(sim, w, self._rng, eps))
            guard += 1
        had_token = sim.state.players[me].has_first_player_token
        score_round(sim)
        sim.state.players[me].has_first_player_token = had_token   # score_round clears it; value it
        return self._leaf_value(sim, me)

    # -- decision -----------------------------------------------------------------
    async def decide(self, game_state: GameStateData, player_index: int) -> GameAction:
        legal = get_legal_actions(game_state, player_index)
        if not legal:
            raise ValueError("No legal actions available")
        player = game_state.players[player_index]
        ranked = sorted(((a, _score_action(game_state, player, a, self.weights)) for a in legal),
                        key=lambda x: x[1], reverse=True)
        shortlist = ranked[: self.candidates]
        # the best floor dump is always worth a look: sometimes it is the only way to deny/avoid
        floor = next((x for x in ranked if x[0].destination.value == "floor"), None)
        if floor and floor not in shortlist:
            shortlist.append(floor)

        start = time.monotonic()
        opp = self.opponent_weights(game_state)
        results: List[Tuple[GameAction, float, float]] = []
        for action, h in shortlist:
            vals = []
            for r in range(self.rollouts):
                if vals and time.monotonic() - start > self.time_budget_s:
                    break
                vals.append(self._rollout(game_state, player_index, action, explore=r > 0, opp=opp))
            results.append((action, sum(vals) / len(vals), h))

        results.sort(key=lambda x: (x[1], x[2]), reverse=True)
        best, value, h = results[0]
        self.last_explanation = {
            "model": self.name,
            "chosen_score": round(value, 2),
            "n_legal": len(legal),
            "method": f"{len(shortlist)} candidates x {self.rollouts} round-end rollouts",
            "top_alternatives": [
                {"action": a.model_dump(), "score": round(v, 2)} for a, v, _ in results[:3]
            ],
        }
        logger.info(f"[{self.name}] {best.color.value} {best.source_type.value}[{best.source_index}] -> "
                    f"{best.destination.value}[{best.destination_row}] value={value:.1f} "
                    f"(heuristic {h:.1f}, {len(legal)} legal)")
        return best
