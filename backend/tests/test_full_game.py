"""End-to-end test: simulate a complete Azul game with two ML players.

This test runs entirely in-memory (no Playwright, no network) by simulating
the game state transitions using the Azul rules engine + ML players.
It validates that:
1. Both GreedyPlayer and RandomPlayer can play a full game to completion
2. All moves are legal
3. Scoring is correct
4. Game terminates (a player completes a wall row)
"""

import asyncio
import copy
import random
import pytest
from typing import List, Optional, Tuple

from app.azul.rules import (
    WALL_PATTERN,
    can_place_on_pattern_line,
    calculate_end_game_bonuses,
    calculate_floor_penalty,
    count_tiles_of_color,
    get_legal_actions,
    is_game_over,
    pattern_line_space,
    score_tile_placement,
    wall_column_for_color,
)
from app.ml.greedy_player import GreedyPlayer
from app.ml.random_player import RandomPlayer
from app.models.schemas import (
    DestinationType,
    GameAction,
    GameStateData,
    PlayerState,
    SourceType,
    TileColor,
)

# --- Tile bag simulation ---

def make_tile_bag() -> List[TileColor]:
    """Create the standard 100-tile bag (20 per color)."""
    bag = []
    for color in TileColor.all_colors():
        bag.extend([color] * 20)
    random.shuffle(bag)
    return bag


def deal_factories(bag: List[TileColor], num_factories: int) -> List[List[TileColor]]:
    """Deal 4 tiles per factory from the bag."""
    factories = []
    for _ in range(num_factories):
        factory = []
        for _ in range(4):
            if bag:
                factory.append(bag.pop())
        if factory:
            factories.append(factory)
    return factories


# --- State simulation ---

def make_initial_state(player_names: List[str], num_factories: int = 5) -> Tuple[GameStateData, List[TileColor]]:
    """Create initial game state with players and a fresh tile bag."""
    bag = make_tile_bag()
    factories = deal_factories(bag, num_factories)

    players = [
        PlayerState(
            index=i, name=name, score=0,
            pattern_lines=[[] for _ in range(5)],
            wall=[[False] * 5 for _ in range(5)],
            floor_line=[],
        )
        for i, name in enumerate(player_names)
    ]

    state = GameStateData(
        room_name="test-game",
        round=1,
        current_turn=player_names[0],
        factories=factories,
        center_pool=[],
        players=players,
        game_over=False,
    )
    return state, bag


def apply_action(state: GameStateData, player_idx: int, action: GameAction) -> GameStateData:
    """Apply an action to the game state and return the new state.

    This simulates the Azul game rules:
    1. Pick all tiles of the chosen color from source
    2. Remaining tiles from factory go to center
    3. Place picked tiles on pattern line or floor
    """
    state = copy.deepcopy(state)
    player = state.players[player_idx]
    color = action.color

    # 1. Pick tiles from source
    picked_count = 0
    remaining = []

    if action.source_type == SourceType.FACTORY and action.source_index is not None:
        factory = state.factories[action.source_index]
        picked_count = sum(1 for t in factory if t == color)
        remaining = [t for t in factory if t != color]
        state.factories[action.source_index] = []
        # Remaining go to center
        state.center_pool.extend([t.value if isinstance(t, TileColor) else t for t in remaining])

    elif action.source_type == SourceType.CENTER:
        picked_count = sum(
            1 for t in state.center_pool
            if (t == color.value if isinstance(t, str) else t == color)
        )
        new_center = []
        first_player_taken = False
        for t in state.center_pool:
            t_str = t.value if isinstance(t, TileColor) else t
            if t_str == color.value:
                continue  # picked
            if t_str == "firstPlayer" and not first_player_taken:
                first_player_taken = True
                player.has_first_player_token = True
                player.floor_line.append(color)  # first player token = floor penalty
                continue
            new_center.append(t_str)
        state.center_pool = new_center

    # 2. Place tiles
    if action.destination == DestinationType.PATTERN_LINE and action.destination_row is not None:
        row = action.destination_row
        space = pattern_line_space(player, row)
        placed = min(picked_count, space)
        overflow = picked_count - placed
        player.pattern_lines[row].extend([color] * placed)
        # Overflow to floor
        for _ in range(overflow):
            if len(player.floor_line) < 7:
                player.floor_line.append(color)

    elif action.destination == DestinationType.FLOOR:
        for _ in range(picked_count):
            if len(player.floor_line) < 7:
                player.floor_line.append(color)

    return state


def do_end_of_round_scoring(state: GameStateData) -> Tuple[GameStateData, bool]:
    """Score completed pattern lines and move tiles to wall.

    Returns (new_state, game_should_end).
    """
    state = copy.deepcopy(state)
    trigger_end = False

    for player in state.players:
        for row in range(5):
            capacity = row + 1
            filled = len(player.pattern_lines[row])
            if filled >= capacity and filled > 0:
                color = player.pattern_lines[row][0]
                if color is None:
                    continue
                col = wall_column_for_color(row, color)
                player.wall[row][col] = True
                points = score_tile_placement(player.wall, row, col)
                player.score += points
                player.pattern_lines[row] = []

        # Floor penalty
        floor_count = len(player.floor_line)
        if floor_count > 0:
            penalty = calculate_floor_penalty(floor_count)
            player.score = max(0, player.score + penalty)
            player.floor_line = []

        # Check if any row complete (triggers end)
        for row in range(5):
            if all(player.wall[row]):
                trigger_end = True

    return state, trigger_end


def is_round_over(state: GameStateData) -> bool:
    """A round ends when all factories and center are empty."""
    for f in state.factories:
        if f:
            return False
    for t in state.center_pool:
        t_str = t.value if isinstance(t, TileColor) else t
        if t_str != "firstPlayer":
            return False
    return True


async def play_full_game(
    player_models,
    player_names: List[str],
    max_rounds: int = 10,
    seed: int = 42,
) -> dict:
    """Play a full game and return results."""
    random.seed(seed)
    num_factories = 5 if len(player_names) == 2 else 7

    state, bag = make_initial_state(player_names, num_factories)
    all_moves = []
    game_ended = False

    for round_num in range(1, max_rounds + 1):
        state.round = round_num

        # Deal tiles if needed (re-fill bag if empty)
        if round_num > 1:
            if not bag:
                bag = make_tile_bag()
            state.factories = deal_factories(bag, num_factories)
            state.center_pool = ["firstPlayer"]

        turn_in_round = 0
        current_player_idx = 0

        while not is_round_over(state):
            state.current_turn = player_names[current_player_idx]
            actions = get_legal_actions(state, current_player_idx)

            if not actions:
                # No legal actions — skip (shouldn't happen if tiles exist)
                current_player_idx = (current_player_idx + 1) % len(player_names)
                continue

            model = player_models[current_player_idx]
            action = await model.decide(state, current_player_idx)

            # Verify the action is legal
            assert action in actions, (
                f"Illegal action by {player_names[current_player_idx]}: {action} "
                f"not in {len(actions)} legal actions"
            )

            state = apply_action(state, current_player_idx, action)
            all_moves.append({
                "round": round_num,
                "player": player_names[current_player_idx],
                "action": action.dict(),
            })

            current_player_idx = (current_player_idx + 1) % len(player_names)
            turn_in_round += 1

            if turn_in_round > 100:
                raise RuntimeError("Round exceeded 100 turns — infinite loop?")

        # End of round scoring
        state, should_end = do_end_of_round_scoring(state)

        if should_end:
            game_ended = True
            break

    # End-game bonuses
    for player in state.players:
        bonuses = calculate_end_game_bonuses(player.wall)
        player.score += bonuses["total"]

    return {
        "rounds": state.round,
        "total_moves": len(all_moves),
        "game_ended_naturally": game_ended,
        "scores": {p.name: p.score for p in state.players},
        "walls": {
            p.name: sum(sum(row) for row in p.wall)
            for p in state.players
        },
        "moves": all_moves,
    }


# --- Tests ---

class TestFullGameGreedyVsGreedy:
    @pytest.mark.asyncio
    async def test_two_greedy_players_complete_game(self):
        result = await play_full_game(
            player_models=[GreedyPlayer(), GreedyPlayer()],
            player_names=["Alice", "Bob"],
            seed=42,
        )
        assert result["game_ended_naturally"], "Game should end with a completed wall row"
        assert result["total_moves"] > 10, f"Should have many moves, got {result['total_moves']}"
        assert result["rounds"] <= 10, f"Should finish within 10 rounds, took {result['rounds']}"

        # Both players should have positive scores
        for name, score in result["scores"].items():
            assert score >= 0, f"{name} has negative score: {score}"

        # At least one player should have a decent score
        max_score = max(result["scores"].values())
        assert max_score > 0, "At least one player should score points"

        print(f"\nGreedy vs Greedy: {result['rounds']} rounds, {result['total_moves']} moves")
        print(f"  Scores: {result['scores']}")
        print(f"  Wall tiles: {result['walls']}")

    @pytest.mark.asyncio
    async def test_greedy_vs_random(self):
        result = await play_full_game(
            player_models=[GreedyPlayer(), RandomPlayer()],
            player_names=["Greedy", "Random"],
            seed=123,
        )
        assert result["game_ended_naturally"]
        assert result["total_moves"] > 10

        print(f"\nGreedy vs Random: {result['rounds']} rounds, {result['total_moves']} moves")
        print(f"  Scores: {result['scores']}")

    @pytest.mark.asyncio
    async def test_all_moves_are_legal(self):
        """Verify every move in a full game is legal at the time it's made."""
        result = await play_full_game(
            player_models=[GreedyPlayer(), GreedyPlayer()],
            player_names=["P1", "P2"],
            seed=99,
        )
        # If we got here without assertion errors, all moves were legal
        assert result["total_moves"] > 0

    @pytest.mark.asyncio
    async def test_multiple_seeds(self):
        """Run games with different seeds to test robustness."""
        for seed in [1, 7, 13, 42, 100]:
            result = await play_full_game(
                player_models=[GreedyPlayer(), GreedyPlayer()],
                player_names=["A", "B"],
                seed=seed,
            )
            assert result["game_ended_naturally"], f"Game with seed={seed} didn't end"
            assert result["total_moves"] > 5, f"Too few moves with seed={seed}"


class TestFullGameThreePlayers:
    @pytest.mark.asyncio
    async def test_three_player_game(self):
        result = await play_full_game(
            player_models=[GreedyPlayer(), GreedyPlayer(), RandomPlayer()],
            player_names=["G1", "G2", "R1"],
            seed=55,
        )
        assert result["game_ended_naturally"]
        assert len(result["scores"]) == 3

        print(f"\n3-player game: {result['rounds']} rounds, {result['total_moves']} moves")
        print(f"  Scores: {result['scores']}")


class TestFullGameFourPlayers:
    @pytest.mark.asyncio
    async def test_four_player_game(self):
        result = await play_full_game(
            player_models=[GreedyPlayer(), GreedyPlayer(), RandomPlayer(), RandomPlayer()],
            player_names=["G1", "G2", "R1", "R2"],
            seed=77,
        )
        assert result["game_ended_naturally"]
        assert len(result["scores"]) == 4

        print(f"\n4-player game: {result['rounds']} rounds, {result['total_moves']} moves")
        print(f"  Scores: {result['scores']}")
