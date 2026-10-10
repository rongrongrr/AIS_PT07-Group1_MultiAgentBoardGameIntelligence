"""Recording moves made by players TILES does not control (humans, or bots from other systems).

Our own bots know what they played. A human's move is only visible as a change in the board, so it is
inferred: of all moves that were legal before, exactly the ones whose simulated result equals the
board we observe afterwards were played. The rules engine does the matching, so an inferred move is
always a legal one. This is what lets the profilers model human opponents.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence

from tiles.azul.game import GameSim, apply_action, finish_game, round_over, score_round
from tiles.azul.rules import get_legal_actions, is_game_over
from tiles.models.schemas import GameAction, GameStateData

logger = logging.getLogger(__name__)


def _val(x) -> str:
    return getattr(x, "value", x)


def _signature(state: GameStateData):
    """The parts of a state that a single drafting move changes."""
    return (
        [sorted(_val(t) for t in f) for f in state.factories],
        sorted(_val(t) for t in state.center_pool),
        [([[_val(t) for t in row if t] for row in p.pattern_lines],
          [_val(t) for t in p.floor_line], bool(p.has_first_player_token)) for p in state.players],
    )


def _scored_signature(state: GameStateData):
    """What a finished round leaves behind: walls, unfinished pattern lines and scores."""
    return [([list(r) for r in p.wall], [[_val(t) for t in row if t] for row in p.pattern_lines], p.score)
            for p in state.players]


def _board_tiles(state: GameStateData, idx: int) -> int:
    p = state.players[idx]
    return sum(1 for row in p.pattern_lines for t in row if t) + len(p.floor_line) + (1 if p.has_first_player_token else 0)


def infer_action(before: GameStateData, after: GameStateData, player_index: int) -> Optional[GameAction]:
    """The move by ``player_index`` that turns ``before`` into ``after``, or None if none matches
    (for example when the move ended the round and the board was already tiled and redealt)."""
    target = _signature(after)
    for action in get_legal_actions(before, player_index):
        sim = GameSim(state=before.model_copy(deep=True), bag=[], current=player_index)
        try:
            apply_action(sim, action)
        except ValueError:
            continue
        if _signature(sim.state) == target:
            return action
    # The move may have been the last of the round: the platform then shows the board already tiled
    # and scored. Match against the result of scoring the round after each candidate move.
    scored_target = _scored_signature(after)
    for action in get_legal_actions(before, player_index):
        sim = GameSim(state=before.model_copy(deep=True), bag=[], current=player_index)
        try:
            apply_action(sim, action)
        except ValueError:
            continue
        if round_over(sim.state):
            score_round(sim)
            if _scored_signature(sim.state) == scored_target:
                return action
            if is_game_over(sim.state):                      # final round: end-of-game bonuses are added too
                finish_game(sim)
                if _scored_signature(sim.state) == scored_target:
                    return action
    return None


@dataclass
class ObservedMove:
    player_index: int
    player_name: str
    before: GameStateData
    action: GameAction


class HumanMoveTracker:
    """Watches the shared board and reports each move made by a player outside ``known_names``."""

    def __init__(self, known_names: Sequence[str]):
        self.known = set(known_names)
        self._pending: Optional[GameStateData] = None
        self.unrecorded = 0

    def update(self, state: Optional[GameStateData]) -> List[ObservedMove]:
        if state is None or not state.players or (state.game_over and self._pending is None):
            self._pending = None
            return []
        out: List[ObservedMove] = []
        names = [p.name for p in state.players]
        if self._pending is not None:
            before = self._pending
            mover = before.current_turn
            if mover in names and (state.current_turn != mover or self._moved(before, state, mover)):
                action = infer_action(before, state, names.index(mover))
                if action is not None:
                    out.append(ObservedMove(names.index(mover), mover, before, action))
                else:
                    self.unrecorded += 1
                    logger.warning("Could not infer %s's move (round ended or board changed unexpectedly)", mover)
                self._pending = None
        has_tiles = any(state.factories) or any(t != "firstPlayer" for t in state.center_pool)
        if self._pending is None and has_tiles and not state.game_over and state.current_turn in names and state.current_turn not in self.known:
            self._pending = state.model_copy(deep=True)
        return out

    @staticmethod
    def _moved(before: GameStateData, after: GameStateData, mover: str) -> bool:
        names = [p.name for p in after.players]
        if mover not in names:
            return False
        i = names.index(mover)
        return _board_tiles(after, i) != _board_tiles(before, i)
