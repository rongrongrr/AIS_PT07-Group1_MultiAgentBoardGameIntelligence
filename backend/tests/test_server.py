"""API server integration tests (local mode, real match on a thread)."""

import time

import pytest
from fastapi.testclient import TestClient

from tiles.server.app import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "tiles.db"))
    with TestClient(app) as test_client:
        yield test_client


def test_health_and_registry(client):
    assert client.get("/api/health").json()["status"] == "ok"
    names = {t["name"] for t in client.get("/api/tacticians").json()}
    assert {"random", "greedy", "minimax", "mcts", "mcts_profiled"} <= names


def test_session_lifecycle_history_and_export(client):
    config = {
        "mode": "local",
        "players": [
            {"name": "A", "tactician": "greedy", "config": {}},
            {"name": "B", "tactician": "random", "config": {}},
        ],
        "profiler": "basic",
        "explainer": "template",
        "seed": 11,
    }
    created = client.post("/api/sessions", json=config)
    assert created.status_code == 201
    session_id = created.json()["id"]

    assert client.post(f"/api/sessions/{session_id}/start").status_code == 200

    deadline = time.time() + 60
    status = None
    while time.time() < deadline:
        status = client.get(f"/api/sessions/{session_id}").json()["status"]
        if status in ("completed", "failed", "aborted"):
            break
        time.sleep(0.2)
    assert status == "completed"

    detail = client.get(f"/api/sessions/{session_id}").json()
    assert detail["result"]["steps"] > 10
    assert detail["state"] is not None
    assert detail["scores"] and detail["winner_name"] in ("A", "B")
    assert detail["players"][0]["tactician"] == "greedy"

    history = client.get(f"/api/history/{session_id}").json()
    moves = history["moves"]
    assert len(moves) == detail["result"]["steps"]
    first = moves[0]
    for key in ("action", "state_before", "state_after", "explanation",
                "report", "timing", "validation"):
        assert key in first, f"TurnRecord missing {key}"

    export = client.get(f"/api/history/{session_id}/export").json()
    assert export["session"]["id"] == session_id
    assert len(export["moves"]) == len(moves)

    profiles = client.get(f"/api/profiles/{session_id}").json()["profiles"]
    assert profiles and all("archetype" in p for p in profiles)


def test_validation_errors(client):
    bad = {
        "mode": "local",
        "players": [{"name": "A", "tactician": "nope", "config": {}}] * 2,
    }
    assert client.post("/api/sessions", json=bad).status_code == 422
    assert client.get("/api/sessions/sess_missing").status_code == 404


def test_websocket_stream(client):
    config = {
        "mode": "local",
        "players": [
            {"name": "A", "tactician": "random", "config": {}},
            {"name": "B", "tactician": "random", "config": {}},
        ],
        "profiler": None,
        "explainer": None,
        "seed": 2,
    }
    session_id = client.post("/api/sessions", json=config).json()["id"]
    with client.websocket_connect(f"/api/sessions/{session_id}/ws") as ws:
        client.post(f"/api/sessions/{session_id}/start")
        types = set()
        deadline = time.time() + 60
        while time.time() < deadline:
            event = ws.receive_json()
            types.add(event["type"])
            if event["type"] == "game_over":
                break
        assert "move" in types and "game_over" in types
