"""API tests for the agents, profiles, rulebook, stats and session
management endpoints (docs/API.md). ``test_server.py`` covers the core
session lifecycle and WebSocket stream."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from tiles.server.app import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "tiles.db"))
    with TestClient(app) as test_client:
        yield test_client


def run_local_session(client, seed=11, profiler="basic", explainer="template"):
    config = {
        "mode": "local",
        "players": [
            {"name": "Greta", "tactician": "greedy", "config": {}},
            {"name": "Randy", "tactician": "random", "config": {"seed": 1}},
        ],
        "profiler": profiler,
        "explainer": explainer,
        "seed": seed,
    }
    session_id = client.post("/api/sessions", json=config).json()["id"]
    assert client.post(f"/api/sessions/{session_id}/start").status_code == 200
    deadline = time.time() + 60
    while time.time() < deadline:
        status = client.get(f"/api/sessions/{session_id}").json()["status"]
        if status in ("completed", "failed", "aborted"):
            break
        time.sleep(0.1)
    assert status == "completed"
    return session_id


# ---------------------------------------------------------------------------
# health / agents
# ---------------------------------------------------------------------------


def test_health_reports_capabilities(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert isinstance(body["live_available"], bool)
    assert isinstance(body["llm_available"], bool)


def test_agents_catalog(client):
    body = client.get("/api/agents").json()
    names = {t["name"] for t in body["tacticians"]}
    assert {"random", "greedy", "minimax", "mcts", "mcts_profiled"} <= names
    mcts = next(t for t in body["tacticians"] if t["name"] == "mcts_profiled")
    assert mcts["uses_opponent_model"] is True
    assert any(p["name"] == "simulations" for p in mcts["params"])
    assert all(t["description"] for t in body["tacticians"])
    assert [p["name"] for p in body["profilers"]] == ["basic"]
    explainers = {e["name"]: e for e in body["explainers"]}
    assert explainers["llm"]["requires"] == "ANTHROPIC_API_KEY"
    assert explainers["template"]["available"] is True
    assert body["validator"]["name"] == "validator"
    legacy = client.get("/api/tacticians").json()
    assert any(t["name"] == "human" for t in legacy)


# ---------------------------------------------------------------------------
# sessions: validation, listing shape, delete
# ---------------------------------------------------------------------------


def test_session_validation_rules(client):
    base = {
        "mode": "local",
        "players": [
            {"name": "A", "tactician": "greedy"},
            {"name": "A", "tactician": "random"},
        ],
    }
    assert client.post("/api/sessions", json=base).status_code == 422  # dup names
    base["players"][1]["name"] = "B"
    base["players"][1]["tactician"] = "human"
    assert client.post("/api/sessions", json=base).status_code == 422  # human local
    live = {
        "mode": "live",
        "players": [
            {"name": "A", "tactician": "human"},
            {"name": "B", "tactician": "human"},
        ],
        "live": {"room_name": "x"},
    }
    assert client.post("/api/sessions", json=live).status_code == 422  # no bots
    live["players"][0]["tactician"] = "greedy"
    created = client.post("/api/sessions", json=live)
    assert created.status_code == 201
    body = created.json()
    assert body["mode"] == "live" and body["status"] == "created"
    assert body["live"]["room_name"] == "x"
    assert body["players"][1]["tactician"] == "human"


def test_list_and_delete_sessions(client):
    session_id = run_local_session(client)
    listed = client.get("/api/sessions").json()
    entry = next(s for s in listed if s["id"] == session_id)
    for key in ("players", "scores", "winner", "winner_name", "steps", "created_at", "status"):
        assert key in entry
    assert entry["status"] == "completed" and entry["steps"] > 10
    assert client.post(f"/api/sessions/{session_id}/start").status_code == 409

    assert client.delete(f"/api/sessions/{session_id}").json() == {"deleted": session_id}
    assert client.get(f"/api/sessions/{session_id}").status_code == 404
    assert client.delete(f"/api/sessions/{session_id}").status_code == 404


def test_history_includes_rounds_and_export_summary(client):
    session_id = run_local_session(client, seed=3)
    history = client.get(f"/api/history/{session_id}").json()
    assert history["session"]["id"] == session_id
    assert len(history["rounds"]) >= 1
    assert history["rounds"][0]["round"] == 1
    assert len(history["moves"]) == history["session"]["steps"]
    export = client.get(f"/api/history/{session_id}/export").json()
    assert export["export_version"] == "2.0"
    assert export["summary"]["winner_name"] in ("Greta", "Randy")


# ---------------------------------------------------------------------------
# profiles: stored + post-hoc analysis
# ---------------------------------------------------------------------------


def test_archetype_catalog(client):
    body = client.get("/api/profiles/archetypes").json()
    assert len(body) == 5
    assert all(a["description"] and a["signature"] for a in body)


def test_profile_analysis_replays_the_ledger(client):
    session_id = run_local_session(client, seed=7, profiler=None)
    # No profiler ran in-game...
    assert client.get(f"/api/profiles/{session_id}").json()["profiles"] == []
    # ...but the analyzer can still profile from the ledger.
    body = client.post(f"/api/profiles/{session_id}/analyze?profiler=basic").json()
    assert body["profiler"] == "basic"
    assert body["moves_analyzed"] > 10 and body["moves_skipped"] == 0
    assert [p["player_name"] for p in body["players"]] == ["Greta", "Randy"]
    greta = body["players"][0]
    assert greta["tactician"] == "greedy"
    assert greta["profile"]["moves_observed"] == greta["stats"]["moves"]
    assert greta["profile"]["archetype"]
    assert len(greta["timeline"]) == greta["stats"]["moves"]
    assert greta["timeline"][-1]["archetype"] == greta["profile"]["archetype"]
    stats = greta["stats"]
    assert abs(sum(stats["color_distribution"].values()) - 1.0) < 1e-6
    assert set(stats["source_split"]) <= {"factory", "center"}
    assert len(stats["score_trajectory"]) == stats["moves"]
    assert stats["final_score"] == stats["score_trajectory"][-1]
    assert stats["avg_legal_actions"] > 0
    assert client.post(f"/api/profiles/{session_id}/analyze?profiler=nope").status_code == 422
    assert client.post("/api/profiles/sess_missing/analyze").status_code == 404


# ---------------------------------------------------------------------------
# rulebook
# ---------------------------------------------------------------------------


def test_rulebook_endpoints(client):
    sections = client.get("/api/rulebook").json()["sections"]
    assert any(s["id"] == "drafting" for s in sections)
    assert all(s["title"] and s["text"] for s in sections)

    search = client.get("/api/rulebook/search", params={"q": "floor line penalty", "k": 3}).json()
    assert search["results"] and search["results"][0]["score"] > 0
    assert "floor" in search["results"][0]["text"].lower()

    rules = client.get("/api/rulebook/rules").json()
    assert rules["extractor"] == "deterministic"
    assert rules["accuracy"] == 1.0 and rules["verified"] == rules["checked"] >= 19
    assert all(r["status"] == "verified" for r in rules["rules"])
    floor = next(r for r in rules["rules"] if r["id"] == "floor_penalties")
    assert floor["parameters"]["penalties"] == [-1, -1, -2, -2, -2, -3, -3]


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


def test_stats_empty_then_populated(client):
    empty = client.get("/api/stats").json()
    assert empty["sessions"]["total"] == 0 and empty["moves_total"] == 0
    assert empty["tacticians"] == [] and empty["recent_sessions"] == []

    session_id = run_local_session(client, seed=5)
    stats = client.get("/api/stats").json()
    assert stats["sessions"]["total"] == 1
    assert stats["sessions"]["by_status"] == {"completed": 1}
    assert stats["moves_total"] > 10
    names = {t["name"]: t for t in stats["tacticians"]}
    assert names["greedy"]["games"] == 1 and names["random"]["games"] == 1
    assert names["greedy"]["wins"] + names["random"]["wins"] == 1
    assert stats["latency"]["decide_ms"]["n"] == stats["moves_total"]
    assert stats["latency"]["total_ms"]["p90"] >= stats["latency"]["total_ms"]["p50"]
    assert sum(stats["archetypes"].values()) == 2
    assert stats["recent_sessions"][0]["id"] == session_id


# ---------------------------------------------------------------------------
# experiments through the real app (router wiring + background runner)
# ---------------------------------------------------------------------------


def test_experiment_runs_through_the_app(client):
    kinds = {t["name"] for t in client.get("/api/experiments/types").json()}
    assert "rule_extraction" in kinds and "profiler_ablation" in kinds
    created = client.post(
        "/api/experiments", json={"kind": "rule_extraction", "params": {}}
    )
    assert created.status_code == 201
    run_id = created.json()["id"]
    deadline = time.time() + 30
    run = None
    while time.time() < deadline:
        run = client.get(f"/api/experiments/{run_id}").json()
        if run["status"] in ("completed", "failed", "aborted"):
            break
        time.sleep(0.1)
    assert run and run["status"] == "completed", run
    result = run["result"]
    assert result["summary"] and result["metrics"]["accuracy"] == 1.0
    assert result["tables"] and result["series"]
    listed = client.get("/api/experiments").json()
    assert listed[0]["id"] == run_id and listed[0]["result"] is None
    stats = client.get("/api/stats").json()
    assert stats["experiments"]["total"] == 1
    assert client.delete(f"/api/experiments/{run_id}").json() == {"deleted": run_id}
    assert client.post("/api/experiments", json={"kind": "nope", "params": {}}).status_code == 422
