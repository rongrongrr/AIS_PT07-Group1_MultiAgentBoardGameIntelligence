"""Explanation feedback API and summary statistics."""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.db import Move
from app.routers.feedback import mean_ci


@pytest.fixture
def client(db):
    with TestClient(app) as c:
        yield c


def make_session_with_move(client, db):
    sid = client.post("/api/sessions", json={"room_name": "fb-room", "players": [{"slot": 0, "type": "GreedyPlayer"}]}).json()["id"]
    db.add(Move(session_id=sid, step_id=1, player_name="A", system_tag="MinimaxPlayer",
                action_json=json.dumps({"source_type": "factory", "source_index": 0, "color": "red",
                                        "destination": "floor", "destination_row": None}), decision_time_ms=1))
    db.commit()
    return sid


def body(sid, rater="p1", u=4, us=5, t=3, comment=None):
    return {"session_id": sid, "step_id": 1, "rater": rater, "understandable": u, "useful": us,
            "trustworthy": t, "comment": comment}


def test_mean_ci_edge_cases():
    assert mean_ci([]) == {"n": 0, "mean": None, "ci95": None}
    assert mean_ci([4]) == {"n": 1, "mean": 4, "ci95": None}
    s = mean_ci([3, 4, 5, 4])
    assert s["mean"] == 4 and s["ci95"][0] < 4 < s["ci95"][1]


def test_submit_and_summarise(client, db):
    sid = make_session_with_move(client, db)
    assert client.post("/api/feedback", json=body(sid, "p1", 4, 5, 3, "clear")).status_code == 200
    assert client.post("/api/feedback", json=body(sid, "p2", 2, 3, 5)).status_code == 200
    summary = client.get("/api/feedback/summary").json()
    assert summary["ratings"] == 2 and summary["raters"] == 2
    assert summary["overall"]["understandable"]["mean"] == 3
    assert summary["by_model"]["MinimaxPlayer"]["trustworthy"]["n"] == 2
    listed = client.get(f"/api/feedback/{sid}").json()
    assert {r["rater"] for r in listed} == {"p1", "p2"} and "clear" in {r["comment"] for r in listed}


@pytest.mark.parametrize("patch", [{"understandable": 0}, {"useful": 6}, {"rater": ""}, {"trustworthy": "x"}])
def test_validation_rejects_bad_ratings(client, db, patch):
    sid = make_session_with_move(client, db)
    assert client.post("/api/feedback", json={**body(sid), **patch}).status_code == 422


def test_unknown_move_is_404_and_empty_summary_is_safe(client, db):
    assert client.post("/api/feedback", json=body("nope")).status_code == 404
    s = client.get("/api/feedback/summary").json()
    assert s["ratings"] == 0 and s["overall"]["useful"]["n"] == 0
