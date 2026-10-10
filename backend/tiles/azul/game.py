"""Azul state transitions: applying moves, round scoring, and full-game simulation.

rules.py answers "what is legal and what does it score"; this module answers
"what is the next state". Together they give search players (MCTS/minimax) and
the tournament runner a complete, deterministic-given-a-seed environment.

Conventions
-----------
* ``GameStateData.center_pool`` holds colour strings plus at most one
  ``"firstPlayer"`` token.
* The first-player token occupies the first floor slot of whoever took it, so it
  counts towards floor penalties (``PlayerState.has_first_player_token``).
* Tiles that leave play (overflow, leftover pattern-line tiles, floor tiles) go
  to the lid and are reshuffled into the bag when the bag runs out.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional, Sequence

from tiles.azul.config import DEFAULT_RULES, RulesConfig
from tiles.azul.rules import (
    calculate_end_game_bonuses,
    calculate_floor_penalty,
    is_game_over,
    pattern_line_space,
    score_tile_placement,
    wall_column_for_color,
)
from tiles.models.schemas import (
    DestinationType,
    GameAction,
    GameStateData,
    PlayerState,
    SourceType,
    TileColor,
)

FIRST_PLAYER = "firstPlayer"
TILES_PER_COLOR = DEFAULT_RULES.tiles_per_color
TILES_PER_FACTORY = DEFAULT_RULES.tiles_per_factory
FLOOR_SLOTS = 7


def factory_count(num_players: int, rules: RulesConfig = DEFAULT_RULES) -> int:
    return rules.factory_count(num_players)


def _val(t) -> str:
    return getattr(t, "value", t)


def floor_size(player: PlayerState) -> int:
    """Occupied floor slots, including the first-player token."""
    return len(player.floor_line) + (1 if player.has_first_player_token else 0)


@dataclass
class GameSim:
    """A game in progress: public state plus the hidden bag/lid and RNG."""

    state: GameStateData
    bag: List[TileColor]
    lid: List[TileColor] = field(default_factory=list)
    rng: random.Random = field(default_factory=random.Random)
    current: int = 0  # index of the player to move
    finished: bool = False
    rules: RulesConfig = DEFAULT_RULES

    def copy(self) -> "GameSim":
        c = GameSim(
            state=self.state.model_copy(deep=True),
            bag=list(self.bag),
            lid=list(self.lid),
            rng=random.Random(),
            current=self.current,
            finished=self.finished,
            rules=self.rules,
        )
        c.rng.setstate(self.rng.getstate())
        return c


def new_game(player_names: Sequence[str], seed: Optional[int] = None,
             rules: RulesConfig = DEFAULT_RULES) -> GameSim:
    if not 2 <= len(player_names) <= 4:
        raise ValueError("Azul supports 2-4 players")
    rng = random.Random(seed)
    bag = [c for c in TileColor.all_colors() for _ in range(rules.tiles_per_color)]
    rng.shuffle(bag)
    players = [PlayerState(index=i, name=n) for i, n in enumerate(player_names)]
    sim = GameSim(
        state=GameStateData(room_name="sim", players=players, round=0),
        bag=bag,
        rng=rng,
        rules=rules,
    )
    deal_round(sim)
    return sim


def _draw(sim: GameSim) -> Optional[TileColor]:
    if not sim.bag and sim.lid:
        sim.bag = sim.lid
        sim.lid = []
        sim.rng.shuffle(sim.bag)
    return sim.bag.pop() if sim.bag else None


def deal_round(sim: GameSim) -> None:
    """Fill the factories and put the first-player token in the center."""
    s = sim.state
    s.round += 1
    s.factories = []
    for _ in range(factory_count(len(s.players), sim.rules)):
        tiles = []
        for _ in range(sim.rules.tiles_per_factory):
            t = _draw(sim)
            if t is not None:
                tiles.append(t)
        s.factories.append(tiles)
    s.center_pool = [FIRST_PLAYER]
    for p in s.players:
        p.has_first_player_token = False
    s.current_turn = s.players[sim.current].name


def round_over(state: GameStateData) -> bool:
    return not any(state.factories) and all(t == FIRST_PLAYER for t in state.center_pool)


def apply_action(sim: GameSim, action: GameAction) -> None:
    """Apply the current player's action in place and advance the turn."""
    s = sim.state
    player = s.players[sim.current]
    color = action.color

    if action.source_type == SourceType.FACTORY:
        factory = s.factories[action.source_index]
        picked = [t for t in factory if t == color]
        rest = [t for t in factory if t != color]
        if not picked:
            raise ValueError(f"No {color.value} tiles in factory {action.source_index}")
        s.factories[action.source_index] = []
        s.center_pool.extend(_val(t) for t in rest)
    else:
        picked = [t for t in s.center_pool if t == color.value]
        if not picked:
            raise ValueError(f"No {color.value} tiles in center")
        if FIRST_PLAYER in s.center_pool:
            player.has_first_player_token = True
        s.center_pool = [t for t in s.center_pool if t != color.value and t != FIRST_PLAYER]

    n = len(picked)
    if action.destination == DestinationType.PATTERN_LINE:
        row = action.destination_row
        placed = min(n, pattern_line_space(player, row))
        player.pattern_lines[row].extend([color] * placed)
        overflow = n - placed
    else:
        overflow = n

    for _ in range(overflow):
        if floor_size(player) < FLOOR_SLOTS:
            player.floor_line.append(color)
        else:
            sim.lid.append(color)

    sim.current = (sim.current + 1) % len(s.players)
    s.current_turn = s.players[sim.current].name


def score_round(sim: GameSim) -> None:
    """Wall tiling, floor penalties, lid refill, and choose next round's starter."""
    s = sim.state
    for i, player in enumerate(s.players):
        for row in range(5):
            line = player.pattern_lines[row]
            if len(line) == row + 1:
                color = line[0]
                col = wall_column_for_color(row, color)
                player.wall[row][col] = True
                player.score += score_tile_placement(player.wall, row, col)
                sim.lid.extend(line[1:])
                player.pattern_lines[row] = []

        player.score = max(0, player.score + calculate_floor_penalty(floor_size(player), sim.rules))
        sim.lid.extend(player.floor_line)
        player.floor_line = []
        if player.has_first_player_token:
            sim.current = i
        player.has_first_player_token = False


def finish_game(sim: GameSim) -> Dict[str, int]:
    for p in sim.state.players:
        p.score += calculate_end_game_bonuses(p.wall, sim.rules)["total"]
    sim.finished = True
    sim.state.game_over = True
    return {p.name: p.score for p in sim.state.players}


def step_round_boundary(sim: GameSim) -> bool:
    """Call when ``round_over``. Scores the round and deals the next, or ends the game.

    Returns True if the game ended.
    """
    score_round(sim)
    if is_game_over(sim.state):
        finish_game(sim)
        return True
    deal_round(sim)
    return False


Decider = Callable[[GameStateData, int], Awaitable[GameAction]]


async def play_game(
    deciders: Sequence[Decider],
    player_names: Sequence[str],
    seed: Optional[int] = None,
    max_rounds: int = 20,
    rules: RulesConfig = DEFAULT_RULES,
    on_move: Optional[Callable[[GameSim, int, GameAction], None]] = None,
    observers: Optional[Sequence[Optional[Callable[[dict, str], None]]]] = None,
) -> Dict:
    """Play a full game. ``deciders[i](state, i)`` returns player i's GameAction.

    ``observers[i](record, name_i)`` (optional) is told about every move after it is
    chosen, so adaptive players can model their opponents.
    """
    from tiles.azul.rules import get_legal_actions
    from tiles.ml.archetypes import move_record

    sim = new_game(player_names, seed, rules)
    moves = 0
    while not sim.finished and sim.state.round <= max_rounds:
        while not round_over(sim.state):
            idx = sim.current
            action = await deciders[idx](sim.state, idx)
            if action not in get_legal_actions(sim.state, idx):
                raise ValueError(f"Illegal action by {player_names[idx]}: {action}")
            if on_move:
                on_move(sim, idx, action)
            if observers and any(observers):
                rec = move_record(sim.state, idx, action)
                for i, obs in enumerate(observers):
                    if obs:
                        obs(rec, player_names[i])
            apply_action(sim, action)
            moves += 1
        if step_round_boundary(sim):
            break
    if not sim.finished:
        finish_game(sim)
    scores = {p.name: p.score for p in sim.state.players}
    return {"scores": scores, "rounds": sim.state.round, "moves": moves,
            "ended_naturally": is_game_over(sim.state)}
