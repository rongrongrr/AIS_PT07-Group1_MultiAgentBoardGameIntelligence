"""External models: registration API, the reference action endpoint, and RemotePlayer."""

import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.azul.game import new_game, play_game
from app.azul.rules import get_legal_actions
from app.main import app
from app.ml.greedy_player import GreedyPlayer
from app.ml.registry import registry
from app.ml.remote_player import RemotePlayer
from app.models.db import MLModel
from app.models.schemas import DestinationType, GameAction, SourceType, TileColor
from app.routers.players import load_registered_players


def run(c):
    return asyncio.run(c)


@pytest.fixture
def client(db):
    with TestClient(app) as c:
        yield c
    for n in ("ext-model", "ext-2"):
        registry.unregister_player(n)


def asgi_client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def request_body(sim, idx=0, **extra):
    return {"state": json.loads(sim.state.model_dump_json()), "player_index": idx, **extra}


# ------------------------------------------------------------------ reference endpoint

def test_action_endpoint_returns_a_legal_move(client):
    sim = new_game(["A", "B"], seed=2)
    r = client.post("/api/player/action", json=request_body(sim, model="MinimaxPlayer"))
    assert r.status_code == 200 and r.json()["model"] == "MinimaxPlayer"
    assert GameAction(**r.json()["action"]) in get_legal_actions(sim.state, 0)


def test_action_endpoint_rejects_bad_requests(client):
    sim = new_game(["A", "B"], seed=2)
    assert client.post("/api/player/action", json=request_body(sim, model="Nope")).status_code == 400
    sim.state.factories = [[] for _ in sim.state.factories]
    sim.state.center_pool = []
    assert client.post("/api/player/action", json=request_body(sim)).status_code == 422


# ------------------------------------------------------------------ registration

def test_register_list_use_and_unregister(client, db):
    r = client.post("/api/players/register", json={"name": "ext-model", "url": "http://models.example/act"})
    assert r.status_code == 200 and r.json()["url"] == "http://models.example/act"
    assert "ext-model" in [p["name"] for p in client.get("/api/players").json()["players"]]
    assert db.query(MLModel).filter(MLModel.name == "ext-model").count() == 1
    p = registry.create_player("ext-model")
    assert isinstance(p, RemotePlayer) and p.url == "http://models.example/act" and p is not registry.get_player("ext-model")

    client.post("/api/players/register", json={"name": "ext-model", "url": "http://other/act", "timeout_sec": 3})   # update
    assert db.query(MLModel).filter(MLModel.name == "ext-model").count() == 1
    assert registry.create_player("ext-model").url == "http://other/act"

    registry.unregister_player("ext-model")                                  # simulate a restart
    assert load_registered_players(db) == 1 and registry.get_player("ext-model").url == "http://other/act"

    assert client.delete("/api/players/ext-model").status_code == 200
    assert registry.get_player("ext-model") is None and client.delete("/api/players/ext-model").status_code == 404


@pytest.mark.parametrize("body,status", [
    ({"name": "GreedyPlayer", "url": "http://x/y"}, 409),
    ({"name": "bad name!", "url": "http://x/y"}, 422),
    ({"name": "ok", "url": "ftp://x/y"}, 422),
    ({"name": "ok", "url": "http://x/y", "timeout_sec": 0}, 422),
])
def test_registration_validation(client, body, status):
    assert client.post("/api/players/register", json=body).status_code == status


def test_builtin_players_cannot_be_deleted(client):
    assert client.delete("/api/players/GreedyPlayer").status_code == 404


# ------------------------------------------------------------------ RemotePlayer

def test_remote_player_plays_legal_moves_via_http():
    async def go():
        async with asgi_client() as http:
            p = RemotePlayer("ext-2", "http://test/api/player/action", client=http)
            sim = new_game(["A", "B"], seed=4)
            a = await p.decide(sim.state, 0)
            return sim, a, p

    sim, a, p = run(go())
    assert a in get_legal_actions(sim.state, 0) and p.clone().url == p.url and p.name == "ext-2"


def test_full_game_against_a_remote_model():
    async def go():
        async with asgi_client() as http:
            remote = RemotePlayer("ext-2", "http://test/api/player/action", client=http)
            return await play_game([remote.decide, GreedyPlayer().decide], ["R", "G"], seed=3)

    res = run(go())
    assert res["ended_naturally"] and set(res["scores"]) == {"R", "G"}


def test_remote_player_rejects_illegal_answers_errors_and_bare_actions():
    sim = new_game(["A", "B"], seed=5)
    legal = get_legal_actions(sim.state, 0)
    illegal = GameAction(source_type=SourceType.FACTORY, source_index=99, color=TileColor.RED,
                         destination=DestinationType.FLOOR).model_dump(mode="json")

    def handler(reply):
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda req: reply(req)))

    async def decide(reply):
        async with handler(reply) as http:
            return await RemotePlayer("x", "http://m/act", client=http).decide(sim.state, 0)

    with pytest.raises(ValueError, match="illegal"):
        run(decide(lambda r: httpx.Response(200, json={"action": illegal})))
    with pytest.raises(httpx.HTTPStatusError):
        run(decide(lambda r: httpx.Response(500)))
    bare = legal[0].model_dump(mode="json")
    assert run(decide(lambda r: httpx.Response(200, json=bare))) == legal[0]          # bare action accepted
    seen = {}

    def capture(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"action": bare})

    run(decide(capture))
    assert seen["body"]["player_index"] == 0 and len(seen["body"]["legal_actions"]) == len(legal)

    sim.state.factories = [[] for _ in sim.state.factories]
    sim.state.center_pool = []
    with pytest.raises(ValueError):
        run(RemotePlayer("x", "http://m/act").decide(sim.state, 0))
