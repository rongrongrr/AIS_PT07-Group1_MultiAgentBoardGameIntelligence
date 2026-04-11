"""Integration tests for the TILES session lifecycle.

These tests verify the full API flow: create session -> start -> check status.
The actual Playwright game execution requires a live connection to buddyboardgames.com,
so we test the API layer and verify the engine components are wired correctly.
"""

import asyncio
import os
import pytest

os.environ["TILES_DB_PATH"] = "/tmp/tiles_integration_test.db"

from fastapi.testclient import TestClient

from app.main import app
from app.models.db import Base, engine, init_db
from app.ml.random_player import RandomPlayer
from app.ml.greedy_player import GreedyPlayer
from app.ml.registry import registry
from app.azul.rules import get_legal_actions
from app.engine.state_parser import parse_game_state_from_event
from app.models.schemas import (
    DestinationType,
    GameStateData,
    PlayerState,
    SourceType,
    TileColor,
)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


class TestSessionLifecycle:
    """Test the full session creation and management flow."""

    def test_create_start_stop_lifecycle(self):
        # 1. Create session
        resp = client.post("/api/sessions", json={
            "room_name": "integration-test-room",
            "browser_mode": "headless",
            "players": [
                {"slot": 0, "type": "RandomPlayer", "name": "TestBot"},
            ],
        })
        assert resp.status_code == 200
        session = resp.json()
        assert session["status"] == "created"
        session_id = session["id"]

        # 2. Verify it appears in the list
        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        ids = [s["id"] for s in resp.json()]
        assert session_id in ids

        # 3. Get session details
        resp = client.get(f"/api/sessions/{session_id}")
        assert resp.status_code == 200
        assert resp.json()["room_name"] == "integration-test-room"

        # 4. Check history is empty
        resp = client.get(f"/api/history/{session_id}")
        assert resp.status_code == 200
        assert resp.json()["total_moves"] == 0

        # 5. Stop session (even though it hasn't been started via browser)
        resp = client.post(f"/api/sessions/{session_id}/stop")
        assert resp.status_code == 200
        assert resp.json()["status"] == "stopped"

        # 6. Verify status updated
        resp = client.get(f"/api/sessions/{session_id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "aborted"

    def test_cannot_start_without_machine_player(self):
        resp = client.post("/api/sessions", json={
            "room_name": "human-only-room",
            "players": [
                {"slot": 0, "type": "human", "name": "Alice"},
            ],
        })
        session_id = resp.json()["id"]

        # Starting with only human players should fail
        resp = client.post(f"/api/sessions/{session_id}/start")
        assert resp.status_code == 400
        assert "machine player" in resp.json()["detail"].lower()

    def test_cannot_start_with_unknown_model(self):
        resp = client.post("/api/sessions", json={
            "room_name": "unknown-model-room",
            "players": [
                {"slot": 0, "type": "NonExistentModel", "name": "Bot"},
            ],
        })
        session_id = resp.json()["id"]

        resp = client.post(f"/api/sessions/{session_id}/start")
        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"].lower()

    def test_headed_mode_persists(self):
        resp = client.post("/api/sessions", json={
            "room_name": "headed-room",
            "browser_mode": "headed",
            "players": [{"slot": 0, "type": "RandomPlayer", "name": "Bot"}],
        })
        session_id = resp.json()["id"]

        resp = client.get(f"/api/sessions/{session_id}")
        assert resp.json()["browser_mode"] == "headed"


class TestRandomPlayerIntegration:
    """Test that RandomPlayer correctly generates actions for various game states."""

    @pytest.fixture
    def player(self):
        return RandomPlayer()

    def test_random_player_registered(self):
        assert registry.get_player("RandomPlayer") is not None

    def test_greedy_player_registered(self):
        assert registry.get_player("GreedyPlayer") is not None

    @pytest.mark.asyncio
    async def test_random_player_decides_from_factory(self, player):
        state = GameStateData(
            room_name="test",
            current_turn="Bot",
            factories=[
                [TileColor.BLUE, TileColor.BLUE, TileColor.RED, TileColor.YELLOW],
                [TileColor.BLACK, TileColor.WHITE, TileColor.WHITE, TileColor.RED],
            ],
            center_pool=[],
            players=[
                PlayerState(index=0, name="Bot", score=0),
            ],
        )

        action = await player.decide(state, 0)
        assert action.source_type == SourceType.FACTORY
        assert action.color in TileColor.all_colors()

    @pytest.mark.asyncio
    async def test_random_player_decides_from_center(self, player):
        state = GameStateData(
            room_name="test",
            current_turn="Bot",
            factories=[],
            center_pool=["red", "red", "blue", "firstPlayer"],
            players=[
                PlayerState(index=0, name="Bot", score=0),
            ],
        )

        action = await player.decide(state, 0)
        assert action.source_type == SourceType.CENTER

    @pytest.mark.asyncio
    async def test_random_player_raises_on_no_moves(self, player):
        state = GameStateData(
            room_name="test",
            current_turn="Bot",
            factories=[],
            center_pool=[],
            players=[PlayerState(index=0, name="Bot", score=0)],
        )

        with pytest.raises(ValueError, match="No legal actions"):
            await player.decide(state, 0)


class TestStateParserIntegration:
    """Test parsing real-ish Socket.IO payloads."""

    def test_full_round_trip(self):
        """Simulate a takeTurnResponse and verify it parses into a usable GameState."""
        payload = {
            "success": True,
            "game": {
                "room": "integration-room",
                "currentPlayer": "Bot1",
                "round": 1,
                "gameOver": False,
                "factories": [
                    [{"color": "blue"}, {"color": "blue"}, {"color": "red"}, {"color": "yellow"}],
                    [{"color": "black"}, {"color": "white"}, {"color": "white"}, {"color": "red"}],
                    [{"color": "yellow"}, {"color": "yellow"}, {"color": "black"}, {"color": "blue"}],
                ],
                "center": [],
                "players": {
                    "Bot1": {
                        "name": "Bot1",
                        "score": 0,
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
                            "grid": [
                                [{"selected": False, "color": c}
                                 for c in ["blue", "yellow", "red", "black", "white"]]
                                for _ in range(5)
                            ]
                        },
                        "floorLine": [],
                        "hasFirstPlayerToken": False,
                    },
                },
            },
        }

        state = parse_game_state_from_event(payload, "sess_test")
        assert state is not None
        assert state.room_name == "integration-room"
        assert len(state.factories) == 3
        assert len(state.players) == 1

        # Verify we can generate legal actions from this state
        actions = get_legal_actions(state, 0)
        assert len(actions) > 0

        # Every action should be valid
        for a in actions:
            assert a.color in TileColor.all_colors()
            assert a.source_type in (SourceType.FACTORY, SourceType.CENTER)
            assert a.destination in (DestinationType.PATTERN_LINE, DestinationType.FLOOR)
