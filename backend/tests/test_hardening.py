"""Behaviour found missing in the final audit: ledger immutability, orphaned sessions, winner tie-break,
session limits, off-loop search, per-move time limits and URL / name hardening."""

import asyncio
import time

import pytest
import sqlalchemy
from fastapi.testclient import TestClient
from sqlalchemy.exc import DatabaseError

from tests.fakes import FakeClock, FakeMP, FakePlatform
from tests.test_orchestration import BotWithHumanOpponent, make_session, run_game
from tiles.bridge import TilesMCTSPlayer
from tiles.main import _abort_orphaned_sessions, app
from tiles.ml.base import MachinePlayer
from tiles.ml.mcts_player import MCTSPlayer
from tiles.ml.minimax_player import MinimaxPlayer
from tiles.ml.registry import registry
from tiles.models.db import Move, Session, get_db
from tiles.models.schemas import DestinationType, GameAction, GameStateData, PlayerState, SourceType, TileColor
from tiles.routers import sessions as S
from tiles.validation import check_platform_url, check_remote_model_url


def add_session(db, status, sid="s1"):
    db.add(Session(id=sid, room_name="r", platform_url="https://buddyboardgames.com/azul", browser_mode="headless",
                   status=status, player_config="[]", move_timeout_sec=5, stuck_abort_sec=2))
    db.commit()


# ------------------------------------------------------------ ledger

def test_move_ledger_is_append_only(db):
    add_session(db, "playing")
    db.add(Move(session_id="s1", step_id=1, player_name="A", action_json="{}"))
    db.commit()
    for stmt in ("UPDATE moves SET player_name='B'", "DELETE FROM moves"):
        with pytest.raises(DatabaseError, match="append-only"):
            db.execute(sqlalchemy.text(stmt))
            db.commit()
        db.rollback()
    assert db.query(Move).count() == 1


# ------------------------------------------------------------ restart recovery

def test_orphaned_sessions_are_aborted_on_startup(db):
    add_session(db, "playing", "a")
    add_session(db, "lobby", "b")
    add_session(db, "completed", "c")
    add_session(db, "created", "d")
    assert _abort_orphaned_sessions(db) == 2
    status = {s.id: s.status for s in db.query(Session)}
    assert status == {"a": "aborted", "b": "aborted", "c": "completed", "d": "created"}
    first = db.query(Session).filter_by(id="a").one()
    assert first.completed_at is not None and "restarted" in first.abort_reason


# ------------------------------------------------------------ winner

def test_winner_tie_break_uses_completed_rows():
    assert S.pick_winner({"A": 40, "B": 30}) == "A"
    assert S.pick_winner({"A": 40, "B": 40}, {"A": 1, "B": 2}) == "B"
    assert S.pick_winner({"A": 40, "B": 40}, {"A": 2, "B": 2}) == "A / B"      # shared win
    assert S.pick_winner({}) is None


def test_completed_rows_counts_full_wall_rows():
    p = PlayerState(index=0, name="A", wall=[[True] * 5, [True, True, False, True, True]] + [[False] * 5] * 3)
    assert S._completed_rows(GameStateData(players=[p])) == {"A": 1}
    assert S._completed_rows(None) == {}


# ------------------------------------------------------------ limits

def test_concurrent_session_cap(db, monkeypatch):
    monkeypatch.setattr(S, "MAX_CONCURRENT_SESSIONS", 1)
    monkeypatch.setitem(S._active_sessions, "other", object())
    add_session(db, "created", "s1")
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as c:
            r = c.post("/api/sessions/s1/start")
            assert r.status_code == 429 and "at most 1" in r.json()["detail"].lower()
    finally:
        app.dependency_overrides.clear()


def test_idle_human_session_is_aborted(db, monkeypatch):
    """A human who never moves cannot keep a session open forever."""
    monkeypatch.setattr(S, "HUMAN_IDLE_TIMEOUT_S", 5.0)
    monkeypatch.setattr(S.time, "time", FakeClock().time)
    platform = FakePlatform(["Alice", "Bob"], seed=2)
    bot = BotWithHumanOpponent(platform, "Alice", human_seat=1, is_host=True)
    bot.mute = True                           # the human never plays
    mp = FakeMP(platform, [bot], human_count=1)
    make_session(db, players=[{"slot": 0, "type": "GreedyPlayer", "name": "Alice"},
                              {"slot": 1, "type": "human", "name": "Bob"}])
    row = run_game(db, mp, {"Alice": registry.create_player("GreedyPlayer")})
    assert row.status == "aborted" and "No progress" in row.abort_reason


# ------------------------------------------------------------ search off the event loop

class SlowSearch(MachinePlayer):
    cpu_bound = True

    @property
    def name(self):
        return "SlowSearch"

    async def decide(self, game_state, player_index):
        time.sleep(0.4)                                       # blocking, like tree search
        return GameAction(source_type=SourceType.CENTER, color=TileColor.RED, destination=DestinationType.FLOOR)


def test_cpu_bound_players_do_not_block_the_event_loop_and_can_time_out():
    async def main():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        t = asyncio.create_task(ticker())
        action = await asyncio.wait_for(S._decide(SlowSearch(), GameStateData(), 0), timeout=5)
        timed_out = False
        try:
            await asyncio.wait_for(S._decide(SlowSearch(), GameStateData(), 0), timeout=0.1)
        except asyncio.TimeoutError:
            timed_out = True
        t.cancel()
        return action, ticks, timed_out

    action, ticks, timed_out = asyncio.run(main())
    assert action.color == TileColor.RED
    assert ticks >= 10                      # the loop kept running during the 0.4 s of blocking work
    assert timed_out                        # and the timeout fired instead of being starved


def test_time_limit_hook_shrinks_search_budgets():
    for cls in (MinimaxPlayer, MCTSPlayer):
        p = cls()
        before = p.time_budget_s
        p.set_time_limit(1)
        assert p.time_budget_s == pytest.approx(0.7) and p.time_budget_s < before
        p.set_time_limit(100)
        assert p.time_budget_s == pytest.approx(0.7)                 # never raised again
    t = TilesMCTSPlayer()
    t.set_time_limit(1)
    assert t.time_budget_ms == pytest.approx(700)
    assert TilesMCTSPlayer().clone().time_budget_ms == 2500.0


# ------------------------------------------------------------ URL and name hardening

def test_url_checks(monkeypatch):
    assert check_platform_url("https://buddyboardgames.com/azul") is None
    assert "not allowed" in check_platform_url("http://169.254.169.254/")
    assert "not allowed" in check_platform_url("https://evil.example/azul")
    monkeypatch.setenv("TILES_ALLOWED_PLATFORM_HOSTS", "evil.example")
    assert check_platform_url("https://evil.example/azul") is None
    assert check_remote_model_url("http://localhost:9000/act") is None
    assert check_remote_model_url("https://model.example.com/act") is None
    assert "not allowed" in check_remote_model_url("http://169.254.169.254/latest")
    assert check_remote_model_url("http://metadata.google.internal/") is not None
    assert check_remote_model_url("http:///nohost") is not None


def test_remote_models_cannot_shadow_builtins_or_use_metadata_urls(db):
    with TestClient(app) as c:
        for name in ("TilesMCTS", "GreedyPlayer"):
            r = c.post("/api/players/register", json={"name": name, "url": "http://localhost:9/act"})
            assert r.status_code == 409
        r = c.post("/api/players/register", json={"name": "evil", "url": "http://169.254.169.254/"})
        assert r.status_code == 422
        assert c.delete("/api/players/TilesMCTS").status_code in (403, 404, 409)
