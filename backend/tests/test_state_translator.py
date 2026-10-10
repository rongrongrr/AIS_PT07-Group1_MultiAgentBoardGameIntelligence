"""Live-platform state translation tests (no Playwright required).

Fixtures mirror real buddyboardgames.com takeTurnResponse payloads,
adapted from the Milestone-1 parser test suite.
"""

from tiles.core import (
    BLACK,
    BLUE,
    CENTER,
    FIRST_PLAYER,
    FLOOR,
    RED,
    WHITE,
    YELLOW,
    Action,
    check_action,
    legal_actions,
)
from tiles.engine.protocol import parse_socketio_frame
from tiles.engine.state_translator import (
    action_to_site_moves,
    infer_action,
    site_state_to_game_state,
)


def cell(color=None, selected=False):
    return {"selected": selected, **({"color": color} if color else {})}


def empty_pattern_lines():
    return {"lines": [[cell() for _ in range(r + 1)] for r in range(5)]}


def empty_wall():
    colors = ["blue", "yellow", "red", "black", "white"]
    return {
        "grid": [
            [cell(colors[(c - r) % 5]) for c in range(5)] for r in range(5)
        ]
    }


def make_player(score=0, pattern=None, wall_cells=None, floor=None, fpt=False):
    p = {
        "score": score,
        "patternLines": empty_pattern_lines(),
        "wall": empty_wall(),
        "floorLine": floor or [],
        "hasFirstPlayerToken": fpt,
    }
    for row, color, count in pattern or []:
        for i in range(count):
            p["patternLines"]["lines"][row][i] = cell(color, selected=True)
    for r, c in wall_cells or []:
        p["wall"]["grid"][r][c]["selected"] = True
    return p


def make_site_game(**overrides):
    game = {
        "room": "tiles-test",
        "round": 2,
        "currentPlayer": "Beta",
        "gameOver": False,
        "factories": [
            [{"type": "blue"}, {"type": "blue"}, {"type": "red"}, {"type": "yellow"}],
            [{"type": "black"}, {"type": "black"}, {"type": "white"}, {"type": "blue"}],
            [],
            [],
            [],
        ],
        "center": ["red", {"type": "yellow"}, "firstPlayer"],
        "players": {
            "Alpha": make_player(
                score=14,
                pattern=[(1, "blue", 1), (2, "red", 3)],
                wall_cells=[(0, 2), (2, 0)],
                floor=[{"color": "blue"}],
            ),
            "Beta": make_player(
                score=18,
                pattern=[(0, "white", 1), (3, "red", 2)],
                wall_cells=[(0, 1)],
            ),
        },
    }
    game.update(overrides)
    return game


# ---------------------------------------------------------------------------
# Socket.IO frame parsing
# ---------------------------------------------------------------------------


def test_parse_socketio_frame():
    raw = '42["takeTurnResponse",{"success":true,"game":{"round":1}}]'
    event, payload = parse_socketio_frame(raw)
    assert event == "takeTurnResponse"
    assert payload["game"]["round"] == 1
    assert parse_socketio_frame("2probe") is None
    assert parse_socketio_frame("3") is None
    assert parse_socketio_frame("42{bad json}") is None


# ---------------------------------------------------------------------------
# Site -> GameState
# ---------------------------------------------------------------------------


def test_translate_supply_and_turn():
    state = site_state_to_game_state(make_site_game())
    assert state.num_players == 2
    assert state.round_number == 2
    assert not state.is_game_over
    assert state.current_player == 1  # Beta, by dict order

    assert state.factories[0][BLUE] == 2
    assert state.factories[0][RED] == 1
    assert state.factories[0][YELLOW] == 1
    assert state.factories[1][BLACK] == 2
    assert sum(state.factories[2]) == 0

    assert state.center[RED] == 1 and state.center[YELLOW] == 1
    assert state.center_has_fpt


def test_translate_player_boards():
    state = site_state_to_game_state(make_site_game())
    alpha, beta = state.players
    assert alpha.name == "Alpha" and alpha.score == 14
    assert alpha.pattern_colors[1] == BLUE and alpha.pattern_counts[1] == 1
    assert alpha.pattern_colors[2] == RED and alpha.pattern_counts[2] == 3
    assert alpha.wall_has(0, 2) and alpha.wall_has(2, 0)
    assert not alpha.wall_has(0, 0)
    assert alpha.floor == [BLUE]
    assert beta.pattern_colors[0] == WHITE
    assert beta.pattern_colors[3] == RED and beta.pattern_counts[3] == 2


def test_translate_first_player_token_flag():
    game = make_site_game(center=["red"])
    game["players"]["Alpha"]["hasFirstPlayerToken"] = True
    state = site_state_to_game_state(game)
    assert not state.center_has_fpt
    assert FIRST_PLAYER in state.players[0].floor
    assert state.next_first_player == 0


def test_translate_game_over():
    state = site_state_to_game_state(make_site_game(gameOver=True))
    assert state.is_game_over
    assert legal_actions(state) == []


def test_translate_bag_estimate_conserves_supply():
    state = site_state_to_game_state(make_site_game())
    for color in range(5):
        visible = (
            sum(f[color] for f in state.factories)
            + state.center[color]
            + sum(
                p.pattern_counts[r]
                for p in state.players
                for r in range(5)
                if p.pattern_colors[r] == color
            )
            + sum(
                1 for p in state.players for t in p.floor if t == color
            )
            + sum(
                1
                for p in state.players
                for r in range(5)
                for c in range(5)
                if p.wall_has(r, c) and (c - r) % 5 == color
            )
        )
        assert state.bag[color] + visible == 20


def test_translated_state_yields_coherent_legal_actions():
    state = site_state_to_game_state(make_site_game())
    legal = legal_actions(state)
    assert legal
    assert all(check_action(state, a) is None for a in legal)
    # Beta already has white on pattern row 0 -> can't also start blue there.
    assert Action(0, BLUE, 0) not in legal
    # Row 3 holds red -> blue may not join it.
    assert Action(0, BLUE, 3) not in legal
    assert Action(0, BLUE, 1) in legal


# ---------------------------------------------------------------------------
# Action -> site payloads
# ---------------------------------------------------------------------------


def test_factory_pick_payloads():
    choose, place = action_to_site_moves(Action(2, RED, 3))
    assert choose == {"turnType": "chooseTiles", "tileType": "red", "factory": "2"}
    assert place == {"turnType": "placeTiles", "patternLine": "3"}


def test_center_pick_payloads():
    choose, place = action_to_site_moves(Action(CENTER, YELLOW, 0))
    assert choose == {"turnType": "chooseTiles", "tileType": "yellow", "center": True}
    assert place == {"turnType": "placeTiles", "patternLine": "0"}


def test_floor_placement_payloads():
    choose, place = action_to_site_moves(Action(0, BLUE, FLOOR))
    assert place == {"turnType": "placeTiles", "floorLine": True}


def test_every_legal_action_translates():
    state = site_state_to_game_state(make_site_game())
    for action in legal_actions(state):
        choose, place = action_to_site_moves(action)
        assert choose["turnType"] == "chooseTiles"
        if "factory" in choose:
            idx = int(choose["factory"])
            assert sum(state.factories[idx]) > 0
        else:
            assert choose["center"] is True
        assert place["turnType"] == "placeTiles"


# ---------------------------------------------------------------------------
# Opponent action inference
# ---------------------------------------------------------------------------


def test_infer_factory_pick():
    before = site_state_to_game_state(make_site_game())
    after = before.clone()
    from tiles.core import apply_action

    action = Action(0, BLUE, 1)
    apply_action(after, action)
    inferred = infer_action(before, after, before.current_player)
    assert inferred == action


def test_infer_center_pick_to_floor():
    before = site_state_to_game_state(make_site_game())
    after = before.clone()
    from tiles.core import apply_action

    action = Action(CENTER, RED, FLOOR)
    apply_action(after, action)
    inferred = infer_action(before, after, before.current_player)
    assert inferred == action


def test_infer_returns_none_on_no_change():
    state = site_state_to_game_state(make_site_game())
    assert infer_action(state, state.clone(), 0) is None
