"""Tests for the Socket.IO state parser."""

import pytest

from app.engine.state_parser import (
    parse_game_state_from_event,
    parse_socketio_message,
    parse_start_game_response,
)
from app.models.schemas import TileColor


class TestSocketIOMessageParsing:
    def test_parse_valid_message(self):
        raw = '42["takeTurnResponse",{"success":true,"game":{}}]'
        result = parse_socketio_message(raw)
        assert result is not None
        assert result[0] == "takeTurnResponse"
        assert result[1] == {"success": True, "game": {}}

    def test_parse_non_socketio_message(self):
        assert parse_socketio_message("2probe") is None
        assert parse_socketio_message("3") is None
        assert parse_socketio_message("") is None

    def test_parse_invalid_json(self):
        assert parse_socketio_message("42{invalid}") is None

    def test_parse_join_room(self):
        raw = '42["joinRoomResponse",{"player":"Bot1","success":true}]'
        result = parse_socketio_message(raw)
        assert result[0] == "joinRoomResponse"
        assert result[1]["player"] == "Bot1"


class TestGameStateFromEvent:
    def test_parse_unsuccessful_event(self):
        payload = {"success": False, "message": "Error"}
        assert parse_game_state_from_event(payload) is None

    def test_parse_no_game_object(self):
        payload = {"success": True}
        assert parse_game_state_from_event(payload) is None

    def test_parse_minimal_game(self):
        payload = {
            "success": True,
            "game": {
                "room": "test-room",
                "currentPlayer": "Bot1",
                "round": 2,
                "gameOver": False,
                "factories": [
                    [{"color": "blue"}, {"color": "red"}, {"color": "red"}, {"color": "yellow"}],
                ],
                "center": ["blue", "firstPlayer"],
                "players": {
                    "Bot1": {
                        "name": "Bot1",
                        "score": 5,
                        "patternLines": {
                            "lines": [
                                [{"selected": True, "color": "blue"}],
                                [{"selected": False}, {"selected": False}],
                                [{"selected": False}, {"selected": False}, {"selected": False}],
                                [{"selected": False}, {"selected": False}, {"selected": False}, {"selected": False}],
                                [{"selected": False}, {"selected": False}, {"selected": False}, {"selected": False}, {"selected": False}],
                            ]
                        },
                        "wall": {
                            "grid": [
                                [{"selected": False, "color": "blue"}, {"selected": False, "color": "yellow"},
                                 {"selected": True, "color": "red"}, {"selected": False, "color": "black"},
                                 {"selected": False, "color": "white"}],
                                [{"selected": False}] * 5,
                                [{"selected": False}] * 5,
                                [{"selected": False}] * 5,
                                [{"selected": False}] * 5,
                            ]
                        },
                        "floorLine": [{"color": "yellow"}],
                        "hasFirstPlayerToken": False,
                    }
                },
            },
        }

        state = parse_game_state_from_event(payload, "sess_test")
        assert state is not None
        assert state.room_name == "test-room"
        assert state.current_turn == "Bot1"
        assert state.round == 2
        assert state.game_over is False

        # Factories
        assert len(state.factories) == 1
        assert len(state.factories[0]) == 4

        # Center pool
        assert "blue" in state.center_pool or TileColor.BLUE in state.center_pool

        # Players
        assert len(state.players) == 1
        p = state.players[0]
        assert p.name == "Bot1"
        assert p.score == 5

        # Pattern lines: row 0 has blue
        assert len(p.pattern_lines[0]) == 1
        assert p.pattern_lines[0][0] == TileColor.BLUE

        # Wall: row 0 col 2 (red) is selected
        assert p.wall[0][2] is True
        assert p.wall[0][0] is False

        # Floor: 1 yellow tile
        assert len(p.floor_line) == 1
        assert p.floor_line[0] == TileColor.YELLOW


class TestStartGameResponse:
    def test_parse_start_response(self):
        payload = {
            "success": True,
            "players": [
                {
                    "name": "Bot1",
                    "score": 0,
                    "connected": True,
                    "patternLines": {
                        "lines": [
                            [{"selected": False}],
                            [{"selected": False}, {"selected": False}],
                            [{"selected": False}] * 3,
                            [{"selected": False}] * 4,
                            [{"selected": False}] * 5,
                        ]
                    },
                    "wall": {
                        "grid": [[{"selected": False, "color": c} for c in ["blue", "yellow", "red", "black", "white"]]] * 5
                    },
                    "floorLine": [],
                }
            ],
        }
        state = parse_start_game_response(payload, "test-room", "sess_test")
        assert state is not None
        assert state.room_name == "test-room"
        assert len(state.players) == 1
        assert state.players[0].name == "Bot1"
        assert state.players[0].score == 0
        assert state.game_over is False

    def test_parse_failed_start(self):
        payload = {"success": False, "message": "Not enough players"}
        assert parse_start_game_response(payload, "test-room") is None
