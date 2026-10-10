"""Session lifecycle routes, WebSocket, history/export, profiler and player routes."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tiles.main import app
from tiles.ml.base import ProfilerAgent
from tiles.ml.registry import registry
from tiles.models.db import GameState, Move, Session
from tiles.routers import sessions as S
from tests.fakes import FakeMP, FakePlatform, FakeBot

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import train_archetypes as ta  # noqa: E402


@pytest.fixture
def client(db, monkeypatch):
    async def forever(*a, **k):
        await asyncio.Event().wait()

    monkeypatch.setattr(S, "_run_multi_bot_game", forever)
    with TestClient(app) as c:
        yield c
    S._active_sessions.clear()
    S._session_tasks.clear()
    S._ws_connections.clear()


def create(client, players=None, **kw):
    body = {"room_name": "room-1", "players": players or [
        {"slot": 0, "type": "GreedyPlayer", "name": "Alice"},
        {"slot": 1, "type": "RandomPlayer", "name": "Bob"}], **kw}
    r = client.post("/api/sessions", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ------------------------------------------------------------- session routes

def test_start_then_stop_session(client, db):
    sid = create(client, players=[{"slot": 0, "type": "GreedyPlayer", "name": "A"},
                                  {"slot": 1, "type": "human", "name": "H"}])
    r = client.post(f"/api/sessions/{sid}/start")
    assert r.status_code == 200 and "1 human" in r.json()["message"]
    assert sid in S._active_sessions and sid in S._session_tasks
    assert client.get(f"/api/sessions/{sid}").json()["status"] == "lobby"

    assert client.post(f"/api/sessions/{sid}/start").status_code == 400      # already started

    r = client.post(f"/api/sessions/{sid}/stop")
    assert r.json()["status"] == "stopped"
    assert client.get(f"/api/sessions/{sid}").json()["status"] == "aborted"
    assert sid not in S._active_sessions


def test_stop_does_not_overwrite_finished_session(client, db):
    sid = create(client)
    row = db.query(Session).filter(Session.id == sid).first()
    row.status = "completed"
    db.commit()
    assert client.post(f"/api/sessions/{sid}/stop").json()["status"] == "completed"
    db.expire_all()
    assert db.query(Session).filter(Session.id == sid).first().status == "completed"


def test_unknown_session_routes_404(client):
    for path in ("start", "stop"):
        assert client.post(f"/api/sessions/nope/{path}").status_code == 404


def test_invalid_session_configs_are_rejected_at_creation(client):
    ok = [{"slot": 0, "type": "GreedyPlayer", "name": "A"}, {"slot": 1, "type": "RandomPlayer", "name": "B"}]

    def post(players=ok, **kw):
        return client.post("/api/sessions", json={"room_name": "room-x", "players": players, **kw})

    assert post().status_code == 200
    cases = {
        "needs 2 to 4": [ok[0]],
        "unique": [ok[0], {**ok[1], "slot": 0}],
        "names must be unique": [ok[0], {**ok[1], "name": "a"}],
        "unknown player type": [ok[0], {**ok[1], "type": "Nope"}],
        "machine player": [{"slot": 0, "type": "human", "name": "H1"}, {"slot": 1, "type": "human", "name": "H2"}],
        "may only contain": [{**ok[0], "name": "<b>x</b>"}, ok[1]],
    }
    for fragment, players in cases.items():
        r = post(players)
        assert r.status_code == 422 and fragment in r.json()["detail"], (fragment, r.text)
    assert post(room_name="a/b?c").status_code == 422
    r = post(platform_url="http://169.254.169.254/latest")
    assert r.status_code == 422 and "not allowed" in r.json()["detail"]
    assert post(platform_url="https://buddyboardgames.com/azul").status_code == 200


@pytest.mark.parametrize("body", [
    {"room_name": "x" * 21},
    {"room_name": ""},
    {"room_name": "ok", "move_timeout_sec": 0},
    {"room_name": "ok", "platform_url": "file:///etc/passwd"},
    {"room_name": "ok", "players": [{"slot": 0, "type": "GreedyPlayer", "name": "n" * 17}]},
    {"room_name": "ok", "players": [{"slot": i, "type": "GreedyPlayer"} for i in range(5)]},
])
def test_create_session_validation(client, body):
    body.setdefault("players", [{"slot": 0, "type": "GreedyPlayer"}])
    assert client.post("/api/sessions", json=body).status_code == 422


# ------------------------------------------------------------- websocket + broadcast

def test_websocket_sends_current_state_and_cleans_up(client):
    platform = FakePlatform(["Alice", "Bob"])
    bot = FakeBot(platform, "Alice")
    bot.current_state = platform.sim.state
    S._active_sessions["s1"] = FakeMP(platform, [bot])

    with client.websocket_connect("/api/sessions/s1/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "state_update" and len(first["data"]["factories"]) == 5
        assert len(S._ws_connections["s1"]) == 1
    import time
    for _ in range(100):                                       # server removes it asynchronously
        if not S._ws_connections["s1"]:
            break
        time.sleep(0.02)
    assert S._ws_connections["s1"] == []


def test_broadcast_drops_dead_sockets():
    class Dead:
        async def send_json(self, _):
            raise RuntimeError("closed")

    class Live:
        got = None

        async def send_json(self, m):
            Live.got = m

    S._ws_connections["x"] = [Dead(), Live()]
    asyncio.run(S._broadcast_state_msg("x", {"type": "t"}))
    assert Live.got == {"type": "t"} and len(S._ws_connections["x"]) == 1
    S._ws_connections.clear()


def test_broadcast_move_and_state_payloads():
    from datetime import datetime
    from tiles.models.schemas import DestinationType, GameAction, GameStateData, MoveRecord, SourceType, TileColor

    sent = []

    class Sock:
        async def send_json(self, m):
            sent.append(m)

    S._ws_connections["m"] = [Sock()]
    act = GameAction(source_type=SourceType.CENTER, color=TileColor.RED, destination=DestinationType.FLOOR)
    rec = MoveRecord(session_id="m", step_id=1, player_name="A", action=act, timestamp=datetime(2026, 1, 1))
    asyncio.run(S._broadcast_move("m", rec, extra={"round": 2}))
    asyncio.run(S._broadcast_state("m", GameStateData()))
    assert sent[0]["type"] == "move" and sent[0]["data"]["round"] == 2
    assert sent[0]["data"]["timestamp"].endswith("Z")
    assert sent[1]["type"] == "state_update"
    S._ws_connections.clear()


# ------------------------------------------------------------- history

def add_move(db, sid, step, tiles, scores=None, color="red"):
    board = {"factories": [["red"] * tiles], "center_pool": ["firstPlayer"], "players": []}
    db.add(Move(session_id=sid, step_id=step, player_name="Alice", system_tag="GreedyPlayer",
                action_json=json.dumps({"source_type": "factory", "source_index": 0, "color": color,
                                        "destination": "pattern_line", "destination_row": 0,
                                        "_extra": {"board": board, "scores": scores or {"Alice": step}}}),
                decision_time_ms=1))


def test_export_splits_rounds_on_tile_refill(client, db):
    sid = create(client)
    for step, tiles in enumerate([20, 14, 6, 1, 20, 12, 3], start=1):    # tiles jump = new round
        add_move(db, sid, step, tiles)
    db.commit()
    data = client.get(f"/api/history/{sid}/export").json()
    assert data["summary"]["total_rounds"] == 2
    assert [r["moves"] for r in data["summary"]["rounds"]] == [4, 3]
    assert data["summary"]["final_scores"] == {"Alice": 7}


def test_export_with_no_moves_and_unknown_session(client):
    sid = create(client)
    d = client.get(f"/api/history/{sid}/export").json()
    assert d["summary"]["total_moves"] == 0 and d["summary"]["final_scores"] == {}
    assert client.get("/api/history/nope/export").status_code == 404


def test_state_snapshot_endpoints(client, db):
    sid = create(client)
    for step in (1, 2, 3):
        db.add(GameState(session_id=sid, step_id=step, state_json=json.dumps({"round": step})))
    db.commit()
    assert client.get(f"/api/history/{sid}/state/2").json()["state"] == {"round": 2}
    assert client.get(f"/api/history/{sid}/state/99").status_code == 404
    listed = client.get(f"/api/history/{sid}/states?limit=2&offset=1").json()["states"]
    assert [s["step_id"] for s in listed] == [2, 3]


# ------------------------------------------------------------- profiler + players

def test_profiler_unknown_session_and_analyzer(client):
    assert client.post("/api/profiler/nope/analyze?player_name=A").status_code == 404
    sid = create(client)
    r = client.post(f"/api/profiler/{sid}/analyze?player_name=A&analyzer_name=Nope")
    assert r.status_code == 400 and "Available" in r.json()["detail"]


def test_archetype_analysis_through_api(client, db):
    import asyncio as aio
    game = aio.run(ta.simulate(1, seed=5))[0]
    name = next(iter(game["labels"]))
    sid = create(client)
    for i, m in enumerate(game["moves"], start=1):
        extra = {"board": m["board"], "scores": {}}
        action = dict(m["action"], _extra=extra)
        db.add(Move(session_id=sid, step_id=i, player_name=m["player_name"], system_tag="x",
                    action_json=json.dumps(action), decision_time_ms=1))
    db.commit()
    r = client.post(f"/api/profiler/{sid}/analyze?player_name={name}&analyzer_name=ArchetypeProfileAnalyzer")
    body = r.json()
    assert r.status_code == 200
    assert body["archetype"].endswith("Player") and "archetype_reasons" in body
    assert "Archetype:" in body["summary"]


def test_players_routes_include_profilers(client):
    class P(ProfilerAgent):
        async def observe(self, move_record):
            return None

        async def summarize(self, session_id):
            return {}

        @property
        def name(self):
            return "TestProfiler"

    registry.register_profiler(P())
    try:
        assert {"name": "TestProfiler", "type": "profiler"} in client.get("/api/players").json()["profilers"]
        assert client.get("/api/players/TestProfiler").json() == {"name": "TestProfiler", "type": "profiler"}
        assert registry.get_profiler("TestProfiler") is not None
    finally:
        registry._profilers.pop("TestProfiler", None)


def test_session_insights_and_external_ingest(client, db):
    import asyncio as aio
    game = aio.run(ta.simulate(1, seed=6))[0]
    sid = create(client)
    assert client.get("/api/profiler/nope/insights").status_code == 404
    assert client.get(f"/api/profiler/{sid}/insights").json()["insights"] == []   # no moves yet
    for i, m in enumerate(game["moves"], start=1):
        action = dict(m["action"], _extra={"board": m["board"], "scores": {}})
        db.add(Move(session_id=sid, step_id=i, player_name=m["player_name"], system_tag="x",
                    action_json=json.dumps(action), decision_time_ms=1))
    db.commit()
    body = client.get(f"/api/profiler/{sid}/insights").json()
    assert body["total_moves"] == len(game["moves"]) and len(body["insights"]) == 2
    assert all(i["moves_observed"] > 0 and i["summary"] for i in body["insights"])
    assert client.get(f"/api/profiler/{sid}/insights?analyzer_name=Nope").status_code == 400
    early = client.get(f"/api/profiler/{sid}/insights?upto_step=3").json()
    assert early["total_moves"] == 3

    # push a stream from an external source, move by move
    first = game["moves"][0]
    r = client.post("/api/profiler/ingest", json={
        "stream_id": "ext-1", "player_name": first["player_name"], "action": first["action"],
        "decision_time_ms": 12, "board": first["board"]})
    assert r.status_code == 200 and r.json()["step_id"] == 1
    assert r.json()["insight"]["moves_observed"] == 1
    got = client.get("/api/profiler/stream/ext-1/insights").json()
    assert got["total_moves"] == 1
    assert client.get("/api/profiler/stream/missing/insights").status_code == 404


def test_ingest_limits(client, monkeypatch):
    from tiles.routers import profiler as P
    action = {"source_type": "center", "color": "red", "destination": "floor"}
    monkeypatch.setattr(P, "MAX_STREAMS", 2)
    monkeypatch.setattr(P, "MAX_MOVES_PER_STREAM", 1)
    P._streams.clear()
    for sid in ("a", "b", "c"):
        assert client.post("/api/profiler/ingest", json={"stream_id": sid, "player_name": "X", "action": action}).status_code == 200
    assert set(P._streams) == {"b", "c"}                       # oldest stream evicted
    assert client.post("/api/profiler/ingest", json={"stream_id": "c", "player_name": "X", "action": action}).status_code == 413
    P._streams.clear()


def test_optional_api_key(client, monkeypatch):
    assert client.get("/api/players").status_code == 200                  # auth is off by default
    monkeypatch.setenv("TILES_API_KEY", "s3cret")
    assert client.get("/api/health").status_code == 200                   # health stays open
    assert client.get("/api/players").status_code == 401
    assert client.get("/api/players", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/api/players", headers={"X-API-Key": "s3cret"}).status_code == 200
    sid = create_with_key(client)
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/sessions/{sid}/ws"):
            pass
    with client.websocket_connect(f"/api/sessions/{sid}/ws?api_key=s3cret"):
        pass


def create_with_key(client):
    r = client.post("/api/sessions", headers={"X-API-Key": "s3cret"}, json={"room_name": "auth-room", "players": [
        {"slot": 0, "type": "GreedyPlayer", "name": "A"}, {"slot": 1, "type": "RandomPlayer", "name": "B"}]})
    assert r.status_code == 200
    return r.json()["id"]


def test_tournament_leaderboard(client, tmp_path, monkeypatch):
    from tiles.routers import tournament as T
    monkeypatch.setattr(T, "RESULTS_PATH", tmp_path / "missing.json")
    assert client.get("/api/tournament").json() == {"available": False}
    f = tmp_path / "r.json"
    f.write_text(json.dumps({"ranking": [{"player": "A", "elo": 1500, "mean_score": 50}], "win_rates": {}}))
    monkeypatch.setattr(T, "RESULTS_PATH", f)
    body = client.get("/api/tournament").json()
    assert body["available"] and body["ranking"][0]["player"] == "A"


def test_shipped_leaderboard_file_is_valid():
    from tiles.routers import tournament as T
    data = json.loads(T.RESULTS_PATH.read_text())
    assert data["ranking"] == sorted(data["ranking"], key=lambda r: -r["elo"])
