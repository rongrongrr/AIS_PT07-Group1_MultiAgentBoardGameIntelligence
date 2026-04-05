"""Tests for Azul rules engine."""

import pytest

from app.azul.rules import (
    WALL_PATTERN,
    calculate_end_game_bonuses,
    calculate_floor_penalty,
    can_place_on_pattern_line,
    get_legal_actions,
    is_color_on_wall,
    is_game_over,
    pattern_line_space,
    score_tile_placement,
    wall_column_for_color,
)
from app.models.schemas import (
    DestinationType,
    GameStateData,
    PlayerState,
    SourceType,
    TileColor,
)


# --- Helpers ---

def make_player(
    index=0,
    name="TestPlayer",
    score=0,
    pattern_lines=None,
    wall=None,
    floor_line=None,
) -> PlayerState:
    return PlayerState(
        index=index,
        name=name,
        score=score,
        pattern_lines=pattern_lines or [[] for _ in range(5)],
        wall=wall or [[False] * 5 for _ in range(5)],
        floor_line=floor_line or [],
    )


def make_state(
    players=None,
    factories=None,
    center_pool=None,
    current_turn="TestPlayer",
) -> GameStateData:
    return GameStateData(
        room_name="test-room",
        current_turn=current_turn,
        players=players or [make_player()],
        factories=factories or [],
        center_pool=center_pool or [],
    )


# --- Wall Pattern Tests ---

class TestWallPattern:
    def test_wall_pattern_is_5x5(self):
        assert len(WALL_PATTERN) == 5
        for row in WALL_PATTERN:
            assert len(row) == 5

    def test_each_row_has_all_colors(self):
        all_colors = set(TileColor.all_colors())
        for row in WALL_PATTERN:
            assert set(row) == all_colors

    def test_each_column_has_all_colors(self):
        all_colors = set(TileColor.all_colors())
        for col in range(5):
            column_colors = {WALL_PATTERN[row][col] for row in range(5)}
            assert column_colors == all_colors

    def test_wall_column_for_color_row_0(self):
        assert wall_column_for_color(0, TileColor.BLUE) == 0
        assert wall_column_for_color(0, TileColor.YELLOW) == 1
        assert wall_column_for_color(0, TileColor.RED) == 2
        assert wall_column_for_color(0, TileColor.BLACK) == 3
        assert wall_column_for_color(0, TileColor.WHITE) == 4

    def test_wall_column_shifts_per_row(self):
        # Row 1 shifts: white, blue, yellow, red, black
        assert wall_column_for_color(1, TileColor.WHITE) == 0
        assert wall_column_for_color(1, TileColor.BLUE) == 1


# --- Pattern Line Tests ---

class TestPatternLines:
    def test_empty_pattern_line_space(self):
        player = make_player()
        for row in range(5):
            assert pattern_line_space(player, row) == row + 1

    def test_partially_filled_pattern_line(self):
        player = make_player(
            pattern_lines=[
                [TileColor.BLUE],  # row 0: full (capacity 1)
                [TileColor.RED, None],  # row 1: 1 filled, 1 empty
                [None, None, None],  # row 2: empty
                [None, None, None, None],  # row 3: empty
                [None, None, None, None, None],  # row 4: empty
            ]
        )
        assert pattern_line_space(player, 0) == 0
        assert pattern_line_space(player, 1) == 1
        assert pattern_line_space(player, 2) == 3

    def test_can_place_on_empty_pattern_line(self):
        player = make_player()
        assert can_place_on_pattern_line(player, 0, TileColor.BLUE) is True
        assert can_place_on_pattern_line(player, 4, TileColor.RED) is True

    def test_cannot_place_different_color(self):
        player = make_player(
            pattern_lines=[
                [],
                [TileColor.RED, None],  # row 1 has red
                [], [], [],
            ]
        )
        assert can_place_on_pattern_line(player, 1, TileColor.BLUE) is False
        assert can_place_on_pattern_line(player, 1, TileColor.RED) is True

    def test_cannot_place_if_color_on_wall(self):
        wall = [[False] * 5 for _ in range(5)]
        wall[0][0] = True  # Blue is at (0, 0) in the wall pattern
        player = make_player(wall=wall)
        assert can_place_on_pattern_line(player, 0, TileColor.BLUE) is False

    def test_cannot_place_on_full_line(self):
        player = make_player(
            pattern_lines=[
                [TileColor.BLUE],  # row 0: full
                [], [], [], [],
            ]
        )
        assert can_place_on_pattern_line(player, 0, TileColor.BLUE) is False


# --- Scoring Tests ---

class TestScoring:
    def test_isolated_tile_scores_1(self):
        wall = [[False] * 5 for _ in range(5)]
        wall[2][2] = True
        assert score_tile_placement(wall, 2, 2) == 1

    def test_horizontal_line(self):
        wall = [[False] * 5 for _ in range(5)]
        wall[0][0] = True
        wall[0][1] = True
        wall[0][2] = True  # newly placed
        assert score_tile_placement(wall, 0, 2) == 3

    def test_vertical_line(self):
        wall = [[False] * 5 for _ in range(5)]
        wall[0][0] = True
        wall[1][0] = True
        wall[2][0] = True  # newly placed
        assert score_tile_placement(wall, 2, 0) == 3

    def test_cross_scores_both(self):
        wall = [[False] * 5 for _ in range(5)]
        # Horizontal: (1,0), (1,1), (1,2)
        wall[1][0] = True
        wall[1][1] = True  # placed
        wall[1][2] = True
        # Vertical: (0,1), (1,1), (2,1)
        wall[0][1] = True
        wall[2][1] = True
        # Score at (1,1): h=3 + v=3 = 6
        assert score_tile_placement(wall, 1, 1) == 6

    def test_floor_penalty_0(self):
        assert calculate_floor_penalty(0) == 0

    def test_floor_penalty_1(self):
        assert calculate_floor_penalty(1) == -1

    def test_floor_penalty_3(self):
        assert calculate_floor_penalty(3) == -4  # -1 + -1 + -2

    def test_floor_penalty_7(self):
        assert calculate_floor_penalty(7) == -14  # -1-1-2-2-2-3-3

    def test_floor_penalty_overflow(self):
        # More than 7 tiles still caps at 7 penalties
        assert calculate_floor_penalty(10) == -14


# --- End Game Bonuses ---

class TestEndGameBonuses:
    def test_no_bonuses(self):
        wall = [[False] * 5 for _ in range(5)]
        bonuses = calculate_end_game_bonuses(wall)
        assert bonuses["total"] == 0

    def test_one_complete_row(self):
        wall = [[False] * 5 for _ in range(5)]
        wall[0] = [True] * 5
        bonuses = calculate_end_game_bonuses(wall)
        assert bonuses["horizontal"] == 2
        assert bonuses["vertical"] == 0

    def test_one_complete_column(self):
        wall = [[False] * 5 for _ in range(5)]
        for row in range(5):
            wall[row][0] = True
        bonuses = calculate_end_game_bonuses(wall)
        assert bonuses["vertical"] == 7

    def test_one_complete_color(self):
        wall = [[False] * 5 for _ in range(5)]
        # Place all 5 blue tiles (one per row at their wall positions)
        for row in range(5):
            col = wall_column_for_color(row, TileColor.BLUE)
            wall[row][col] = True
        bonuses = calculate_end_game_bonuses(wall)
        assert bonuses["color"] == 10

    def test_full_wall(self):
        wall = [[True] * 5 for _ in range(5)]
        bonuses = calculate_end_game_bonuses(wall)
        assert bonuses["horizontal"] == 10  # 5 rows * 2
        assert bonuses["vertical"] == 35  # 5 cols * 7
        assert bonuses["color"] == 50  # 5 colors * 10
        assert bonuses["total"] == 95


# --- Legal Actions ---

class TestLegalActions:
    def test_no_tiles_no_actions(self):
        state = make_state(factories=[], center_pool=[])
        actions = get_legal_actions(state, 0)
        assert actions == []

    def test_factory_tiles_generate_actions(self):
        state = make_state(
            factories=[
                [TileColor.BLUE, TileColor.BLUE, TileColor.RED, TileColor.YELLOW],
            ]
        )
        actions = get_legal_actions(state, 0)
        # 3 colors (blue, red, yellow) * (5 pattern lines + 1 floor) = 18 actions
        assert len(actions) == 18

        # All actions should reference factory 0
        for a in actions:
            assert a.source_type == SourceType.FACTORY
            assert a.source_index == 0

        # Check colors present
        colors = {a.color for a in actions}
        assert colors == {TileColor.BLUE, TileColor.RED, TileColor.YELLOW}

    def test_center_pool_generates_actions(self):
        state = make_state(
            factories=[],
            center_pool=["red", "red", "blue", "firstPlayer"],
        )
        actions = get_legal_actions(state, 0)
        # 2 colors (red, blue) * 6 destinations = 12
        assert len(actions) == 12
        for a in actions:
            assert a.source_type == SourceType.CENTER

    def test_wall_blocks_pattern_line(self):
        """If blue is already on wall row 0, can't place blue on pattern line 0."""
        wall = [[False] * 5 for _ in range(5)]
        wall[0][0] = True  # Blue at row 0
        player = make_player(wall=wall)
        state = make_state(
            players=[player],
            factories=[[TileColor.BLUE, TileColor.BLUE, TileColor.RED, TileColor.RED]],
        )
        actions = get_legal_actions(state, 0)
        blue_row0 = [
            a for a in actions
            if a.color == TileColor.BLUE
            and a.destination == DestinationType.PATTERN_LINE
            and a.destination_row == 0
        ]
        assert len(blue_row0) == 0

    def test_floor_always_available(self):
        """Floor should always be an option for any color from any source."""
        state = make_state(
            factories=[[TileColor.RED, TileColor.RED, TileColor.RED, TileColor.RED]]
        )
        actions = get_legal_actions(state, 0)
        floor_actions = [a for a in actions if a.destination == DestinationType.FLOOR]
        assert len(floor_actions) == 1  # Only red from factory 0

    def test_invalid_player_index(self):
        state = make_state()
        assert get_legal_actions(state, 5) == []
        assert get_legal_actions(state, -1) == []


# --- Game Over ---

class TestGameOver:
    def test_not_over_empty_wall(self):
        state = make_state()
        assert is_game_over(state) is False

    def test_over_when_row_complete(self):
        wall = [[False] * 5 for _ in range(5)]
        wall[2] = [True] * 5
        player = make_player(wall=wall)
        state = make_state(players=[player])
        assert is_game_over(state) is True

    def test_over_any_player(self):
        """Game is over if ANY player completes a row."""
        p1 = make_player(index=0, name="P1")
        wall2 = [[False] * 5 for _ in range(5)]
        wall2[0] = [True] * 5
        p2 = make_player(index=1, name="P2", wall=wall2)
        state = make_state(players=[p1, p2])
        assert is_game_over(state) is True
