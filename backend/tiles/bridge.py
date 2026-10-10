"""Bridge between the live-platform data model and the bit-packed core engine.

The live engine (``tiles.engine`` / ``tiles.routers``) works on ``GameStateData`` / ``GameAction``
(the shapes parsed from buddyboardgames.com and stored in the ledger). The decision stack in
``tiles.agents`` (PUCT MCTS, minimax, opponent-move predictor) works on the fast ``tiles.core``
engine. This module converts between the two so the core Tacticians can play real live games:

* ``to_core_state``       GameStateData -> core.GameState (bag estimated from unseen tiles)
* ``to_core_action`` / ``from_core_action``   GameAction <-> core.Action
* ``CoreTacticianPlayer`` wraps a ``Tactician`` as a ``MachinePlayer``; the profiled variant
  feeds every observed opponent move into ``OpponentMovePredictor`` and injects its predictions
  into the search (the proposal's "MCTS with profiler priors").
"""

from __future__ import annotations

import logging
import random
from typing import Dict, List, Optional

from tiles.agents.base import DecisionContext, Tactician
from tiles.agents.profiler.predictor import OpponentMovePredictor
from tiles.agents.tacticians import make_tactician
from tiles.core import (
    CENTER,
    FLOOR,
    NUM_COLORS,
    TILES_PER_COLOR,
    Action,
    GameState,
    PlayerBoard,
    color_from_name,
    legal_actions,
)
from tiles.core.state import FIRST_PLAYER
from tiles.ml.base import MachinePlayer
from tiles.models.schemas import (
    DestinationType,
    GameAction,
    GameStateData,
    SourceType,
    TileColor,
)

logger = logging.getLogger(__name__)

_COLOR_NAMES = ["blue", "yellow", "red", "black", "white"]


def _val(x) -> str:
    return getattr(x, "value", x)


def to_core_state(state: GameStateData, player_index: int) -> GameState:
    """Convert a live ``GameStateData`` into a core ``GameState`` with ``current_player`` set.

    The bag is estimated as every tile not visible on the table (factories, centre, pattern lines,
    walls, floors); the lid is folded into the bag, which matches re-dealing because the lid is
    reshuffled into the bag when the bag runs out.
    """
    core = GameState(num_players=len(state.players))
    core.round_number = state.round
    core.current_player = player_index

    seen = [0] * NUM_COLORS
    for i, f in enumerate(state.factories[: len(core.factories)]):
        for t in f:
            core.factories[i][color_from_name(_val(t))] += 1
    core.center_has_fpt = False
    for t in state.center_pool:
        if t == "firstPlayer":
            core.center_has_fpt = True
        else:
            core.center[color_from_name(_val(t))] += 1
    for color in range(NUM_COLORS):
        seen[color] += sum(f[color] for f in core.factories) + core.center[color]

    for i, p in enumerate(state.players):
        board: PlayerBoard = core.players[i]
        board.name = p.name
        board.score = p.score
        for r, row in enumerate(p.wall):
            for c, filled in enumerate(row):
                if filled:
                    board.wall |= 1 << (r * 5 + c)
                    seen[(c - r) % NUM_COLORS] += 1
        for r, line in enumerate(p.pattern_lines):
            tiles = [t for t in line if t]
            if tiles:
                col = color_from_name(_val(tiles[0]))
                board.pattern_colors[r] = col
                board.pattern_counts[r] = len(tiles)
                seen[col] += len(tiles)
        for t in p.floor_line:
            col = color_from_name(_val(t))
            board.floor.append(col)
            seen[col] += 1
        if p.has_first_player_token:
            board.floor.append(FIRST_PLAYER)

    core.bag = [max(0, TILES_PER_COLOR - seen[c]) for c in range(NUM_COLORS)]
    core.lid = [0] * NUM_COLORS
    return core


def to_core_action(action: GameAction) -> Action:
    return Action(
        source_index=CENTER if action.source_type == SourceType.CENTER else int(action.source_index),
        color=color_from_name(_val(action.color)),
        dest_row=FLOOR if action.destination == DestinationType.FLOOR else int(action.destination_row),
    )


def from_core_action(action: Action) -> GameAction:
    return GameAction(
        source_type=SourceType.CENTER if action.from_center else SourceType.FACTORY,
        source_index=None if action.from_center else action.source_index,
        color=TileColor(_COLOR_NAMES[action.color]),
        destination=DestinationType.FLOOR if action.to_floor else DestinationType.PATTERN_LINE,
        destination_row=None if action.to_floor else action.dest_row,
    )


class CoreTacticianPlayer(MachinePlayer):
    """A core ``Tactician`` playing through the live ``MachinePlayer`` interface."""

    _name = "TilesTactician"
    _tactician = "greedy"

    def __init__(self, seed: Optional[int] = None):
        self.seed = seed
        self._rng = random.Random(seed)
        self.tactician: Tactician = make_tactician(self._tactician)
        self.predictor = OpponentMovePredictor() if self.tactician.uses_opponent_model else None
        self.last_explanation: dict = {}

    @property
    def name(self) -> str:
        return self._name

    def clone(self) -> "CoreTacticianPlayer":
        return type(self)(seed=self.seed)

    # -- opponent observation (profiler priors) -------------------------------------

    def observe(self, record: dict, observer_name: str) -> None:
        if self.predictor is None or record.get("player_name") == observer_name:
            return
        from tiles.ml.archetypes import state_from_record

        try:
            before = state_from_record(record)
            if before is None:
                return
            idx = record["player_index"]
            action = to_core_action(GameAction(**record["action"]))
            self.predictor.observe(to_core_state(before, idx), action, idx)
        except Exception as e:  # observation must never break the game loop
            logger.debug("opponent observation skipped: %s", e)

    # -- decision ---------------------------------------------------------------------

    async def decide(self, game_state: GameStateData, player_index: int) -> GameAction:
        core = to_core_state(game_state, player_index)
        legal: List[Action] = legal_actions(core)
        if not legal:
            raise ValueError("no legal actions")
        ctx = DecisionContext(
            state=core, player_index=player_index, legal=legal,
            opponent_policy=self.predictor.predict if self.predictor else None,
            time_budget_ms=2500.0, rng_seed=self._rng.randrange(1 << 30),
        )
        decision = self.tactician.decide(ctx)
        report = decision.report
        alternatives: List[Dict] = []
        if report:
            for c in report.candidates[:3]:
                alternatives.append({"action": from_core_action(c.action).model_dump(mode="json"),
                                     "score": round(c.score, 3)})
        method = self.tactician.name
        if report:
            method = f"{report.notes.get('strategy', self.tactician.name)}, {report.simulations} simulations"
        self.last_explanation = {
            "model": self.name,
            "n_legal": len(legal),
            "method": method,
            "top_alternatives": alternatives,
            "used_opponent_model": bool(report and report.used_opponent_model),
        }
        if report and report.best is not None:
            self.last_explanation["chosen_score"] = round(report.best.score, 3)
        return from_core_action(decision.action)


class TilesMinimaxPlayer(CoreTacticianPlayer):
    _name = "TilesMinimax"
    _tactician = "minimax"


class TilesMCTSPlayer(CoreTacticianPlayer):
    _name = "TilesMCTS"
    _tactician = "mcts"


class TilesProfiledMCTSPlayer(CoreTacticianPlayer):
    """PUCT MCTS whose opponent nodes are biased by the learned next-move predictor."""

    _name = "TilesProfiledMCTS"
    _tactician = "mcts_profiled"


CORE_PLAYERS = (TilesMinimaxPlayer, TilesMCTSPlayer, TilesProfiledMCTSPlayer)
