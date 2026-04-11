"""Tests for FastAPI API endpoints."""

import os
import pytest
from fastapi.testclient import TestClient

# Use a test database
os.environ["TILES_DB_PATH"] = "/tmp/tiles_test.db"

from app.main import app
from app.models.db import Base, engine, init_db


@pytest.fixture(autouse=True)
def setup_db():
    """Create fresh DB for each test."""
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


class TestHealth:
    def test_health_check(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestSessions:
    def test_create_session(self):
        resp = client.post("/api/sessions", json={
            "room_name": "test-room",
            "players": [
                {"slot": 0, "type": "RandomPlayer", "name": "Bot1"},
            ],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["room_name"] == "test-room"
        assert data["status"] == "created"
        assert data["id"].startswith("sess_")
        assert data["browser_mode"] == "headless"

    def test_create_session_headed(self):
        resp = client.post("/api/sessions", json={
            "room_name": "test-headed",
            "browser_mode": "headed",
            "players": [
                {"slot": 0, "type": "RandomPlayer", "name": "Bot1"},
            ],
        })
        assert resp.status_code == 200
        assert resp.json()["browser_mode"] == "headed"

    def test_list_sessions(self):
        # Create two sessions
        client.post("/api/sessions", json={
            "room_name": "room-1",
            "players": [{"slot": 0, "type": "RandomPlayer"}],
        })
        client.post("/api/sessions", json={
            "room_name": "room-2",
            "players": [{"slot": 0, "type": "RandomPlayer"}],
        })

        resp = client.get("/api/sessions")
        assert resp.status_code == 200
        sessions = resp.json()
        assert len(sessions) == 2

    def test_get_session_not_found(self):
        resp = client.get("/api/sessions/nonexistent")
        assert resp.status_code == 404

    def test_get_session_by_id(self):
        create_resp = client.post("/api/sessions", json={
            "room_name": "test-get",
            "players": [{"slot": 0, "type": "RandomPlayer", "name": "Bot1"}],
        })
        session_id = create_resp.json()["id"]

        resp = client.get(f"/api/sessions/{session_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == session_id


class TestPlayers:
    def test_list_players(self):
        resp = client.get("/api/players")
        assert resp.status_code == 200
        data = resp.json()
        assert "players" in data
        names = [p["name"] for p in data["players"]]
        assert "RandomPlayer" in names

    def test_get_player(self):
        resp = client.get("/api/players/RandomPlayer")
        assert resp.status_code == 200
        assert resp.json()["name"] == "RandomPlayer"

    def test_get_unknown_player(self):
        resp = client.get("/api/players/NonExistent")
        assert resp.status_code == 200
        assert "error" in resp.json()


class TestHistory:
    def test_get_history_not_found(self):
        resp = client.get("/api/history/nonexistent")
        assert resp.status_code == 404

    def test_get_history_empty(self):
        create_resp = client.post("/api/sessions", json={
            "room_name": "test-history",
            "players": [{"slot": 0, "type": "RandomPlayer"}],
        })
        session_id = create_resp.json()["id"]

        resp = client.get(f"/api/history/{session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_moves"] == 0
        assert data["moves"] == []

    def test_history_returns_board_data(self):
        """Board snapshots stored with moves should be returned in history."""
        import json as _json
        create_resp = client.post("/api/sessions", json={
            "room_name": "board-hist",
            "players": [{"slot": 0, "type": "GreedyPlayer", "name": "A"}],
        })
        sid = create_resp.json()["id"]

        # Insert a move with board data directly into DB
        from app.models.db import Move, SessionLocal
        db = SessionLocal()
        move = Move(
            session_id=sid, step_id=1, player_name="Alice",
            system_tag="GreedyPlayer",
            action_json=_json.dumps({
                "source_type": "factory", "source_index": 0,
                "color": "red", "destination": "pattern_line", "destination_row": 0,
                "_extra": {
                    "round": 1,
                    "scores": {"Alice": 5},
                    "board": {
                        "factories": [["red", "blue"]],
                        "center_pool": [],
                        "players": [{
                            "name": "Alice", "score": 5,
                            "pattern_lines": [["red"], [], [], [], []],
                            "wall": [[True] + [False]*4] + [[False]*5]*4,
                            "floor_line": [],
                        }],
                    },
                },
            }),
            decision_time_ms=5,
        )
        db.add(move)
        db.commit()
        db.close()

        resp = client.get(f"/api/history/{sid}")
        data = resp.json()
        assert data["total_moves"] == 1
        m = data["moves"][0]
        assert "board" in m, f"board missing, keys: {list(m.keys())}"
        assert m["board"]["factories"] == [["red", "blue"]]
        assert m["scores"] == {"Alice": 5}
        assert m["round"] == 1

    def test_profiler_analyzers(self):
        resp = client.get("/api/profiler/analyzers")
        assert resp.status_code == 200
        analyzers = resp.json()["analyzers"]
        assert len(analyzers) >= 1
        assert analyzers[0]["name"] == "BasicProfileAnalyzer"

    def test_profiler_analyze(self):
        import json as _json
        create_resp = client.post("/api/sessions", json={
            "room_name": "profile-test",
            "players": [{"slot": 0, "type": "GreedyPlayer", "name": "A"}],
        })
        sid = create_resp.json()["id"]
        from app.models.db import Move, SessionLocal
        db = SessionLocal()
        for i in range(5):
            db.add(Move(
                session_id=sid, step_id=i+1,
                player_name="Alice" if i % 2 == 0 else "Bob",
                system_tag="GreedyPlayer",
                action_json=_json.dumps({
                    "source_type": "factory", "source_index": i % 3,
                    "color": ["red", "blue", "yellow"][i % 3],
                    "destination": "pattern_line", "destination_row": i % 5,
                    "_extra": {"scores": {"Alice": i * 2, "Bob": i}, "total_ms": 1500},
                }),
                decision_time_ms=3,
            ))
        db.commit(); db.close()

        resp = client.post(f"/api/profiler/{sid}/analyze?player_name=Alice")
        assert resp.status_code == 200
        data = resp.json()
        assert data["player_name"] == "Alice"
        assert "summary" in data
        assert data["total_moves"] == 3
        assert "color_preferences" in data

    def test_export_endpoint(self):
        """Export endpoint returns full game data."""
        import json as _json
        create_resp = client.post("/api/sessions", json={
            "room_name": "export-test",
            "players": [{"slot": 0, "type": "GreedyPlayer", "name": "A"}],
        })
        sid = create_resp.json()["id"]

        from app.models.db import Move, SessionLocal
        db = SessionLocal()
        for i in range(3):
            db.add(Move(
                session_id=sid, step_id=i+1, player_name="Alice",
                system_tag="GreedyPlayer",
                action_json=_json.dumps({
                    "source_type": "factory", "source_index": i,
                    "color": "red", "destination": "pattern_line", "destination_row": i,
                    "_extra": {"round": 1, "scores": {"Alice": i*2}},
                }),
                decision_time_ms=5,
            ))
        db.commit()
        db.close()

        resp = client.get(f"/api/history/{sid}/export")
        assert resp.status_code == 200
        data = resp.json()
        assert data["export_version"] == "1.0"
        assert data["session"]["id"] == sid
        assert data["session"]["room_name"] == "export-test"
        assert data["summary"]["total_moves"] == 3
        assert len(data["moves"]) == 3
        assert data["moves"][0]["action"]["color"] == "red"
