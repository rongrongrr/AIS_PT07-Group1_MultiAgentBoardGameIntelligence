"""The platform's current wire format, using frames captured from a real game."""

import asyncio
import json
from pathlib import Path

import pytest

from app.azul.rules import is_game_over
from app.engine import play_engine as pe
from app.engine.state_parser import parse_game_state_from_event, parse_socketio_message
from app.models.schemas import TileColor

FRAMES = json.loads((Path(__file__).parent / "fixtures" / "live_frames.json").read_text())["frames"]
FIRST_DEAL, MID, ROUND_END, NEXT_DEAL, REJECTED_DEAL, FINAL = FRAMES


def parse(frame):
    return parse_game_state_from_event(frame["payload"], "sid")


def test_json_envelope_is_understood():
    raw = json.dumps(FIRST_DEAL)
    name, payload = parse_socketio_message(raw)
    assert name == "takeTurnResponse" and payload["success"] is True
    assert parse_socketio_message('{"no_type": 1}') is None
    assert parse_socketio_message("{broken") is None
    assert parse_socketio_message(b"binary") is None
    assert parse_socketio_message('42["legacy",{"a":1}]') == ("legacy", {"a": 1})


def test_first_deal_state():
    s = parse(FIRST_DEAL)
    assert [p.name for p in s.players] == ["Alice", "Bob"]            # platform seat order
    assert s.current_turn in ("Alice", "Bob")
    assert len(s.factories) == 5 and all(len(f) == 4 for f in s.factories)
    assert s.center_pool == ["firstPlayer"]
    assert s.round_in_progress is True and s.game_over is False
    assert all(p.score == 0 and not any(any(r) for r in p.wall) for p in s.players)


def test_mid_round_state_reads_pattern_lines_and_wall():
    s = parse(MID)
    tiles = sum(len(r) for p in s.players for r in p.pattern_lines)
    assert tiles > 0
    for p in s.players:
        for row, line in enumerate(p.pattern_lines):
            assert len(line) <= row + 1 and all(isinstance(t, TileColor) for t in line)
            assert len(set(line)) <= 1                                  # a line holds one colour


def test_round_end_is_not_game_over_and_next_deal_resumes():
    end, nxt = parse(ROUND_END), parse(NEXT_DEAL)
    assert end.round_in_progress is False and end.game_over is False
    assert nxt.round_in_progress is True and any(nxt.factories)


def test_rejected_deal_still_provides_current_game():
    assert REJECTED_DEAL["payload"]["success"] is False
    s = parse(REJECTED_DEAL)
    assert s is not None and s.round_in_progress is True


def test_final_frame_is_game_over_with_finished_wall_row():
    s = parse(FINAL)
    assert s.game_over and is_game_over(s)
    assert s.round_in_progress is False
    assert max(p.score for p in s.players) > 0


def feed(bot, frame):
    bot._on_ws_frame(json.dumps(frame), "received")


def test_bot_tracks_authoritative_state_round_and_events():
    bot = pe.BotBrowser("sid", "room", "Alice")
    feed(bot, FIRST_DEAL)
    assert bot.round == 1 and bot.ws_state.round_in_progress is True and bot._state_event.is_set()
    assert bot.current_state is bot.ws_state and bot.game_started

    bot._state_event.clear()
    feed(bot, REJECTED_DEAL)                       # carries the game but must not confirm anything
    assert not bot._state_event.is_set() and bot.round == 1

    feed(bot, ROUND_END)
    feed(bot, NEXT_DEAL)
    assert bot.round == 2 and not bot.game_over
    feed(bot, FINAL)
    assert bot.game_over


def test_decisions_use_ws_state_and_scores_are_not_swapped():
    bot = pe.BotBrowser("sid", "room", "Alice")
    feed(bot, FINAL)
    truth = {n: P["score"] for n, P in FINAL["payload"]["game"]["players"].items()}
    assert asyncio.run(bot.get_scores()) == truth
    assert asyncio.run(bot.refresh_state_from_dom()) is bot.ws_state       # no DOM scraping needed
    assert asyncio.run(bot.get_player_index()) == [p.name for p in bot.ws_state.players].index("Alice")
    assert asyncio.run(bot.check_game_over()) is True


def test_needs_deal_follows_authoritative_round_state(monkeypatch):
    bot = pe.BotBrowser("sid", "room", "Alice")
    state = {"empty": True}

    async def empty():
        return state["empty"]

    monkeypatch.setattr(bot, "_board_is_empty", empty)
    feed(bot, ROUND_END)
    assert asyncio.run(bot.needs_deal(settle_ms=1)) is True
    state["empty"] = False                          # stale "round over" but tiles are on the board
    assert asyncio.run(bot.needs_deal(settle_ms=1)) is False
    state["empty"] = True
    feed(bot, NEXT_DEAL)                            # server says a round is running
    assert asyncio.run(bot.needs_deal(settle_ms=1)) is False
    feed(bot, ROUND_END)
    bot._last_deal_at = pe.time.monotonic()         # just dealt: cooldown applies
    assert asyncio.run(bot.needs_deal(settle_ms=1)) is False
