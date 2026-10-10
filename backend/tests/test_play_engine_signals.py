"""Game-over and new-round detection, using a stub page (no browser needed)."""

import asyncio

import pytest

import tiles.engine.play_engine as pe
from tiles.models.schemas import GameStateData, PlayerState


def make_bot(monkeypatch, signals=None, empty=(), dom_state=None):
    """BotBrowser with a fake page. ``empty`` is a sequence of successive board-empty readings."""
    bot = pe.BotBrowser("s", "room", "Bot")
    bot._page = object()  # truthy placeholder; JS-reading methods are stubbed below
    sig = signals or {"strong": False, "weak": False}
    readings = list(empty)

    async def read_signals():
        return sig

    async def board_empty():
        return readings.pop(0) if readings else readings_default

    readings_default = False
    monkeypatch.setattr(bot, "_read_game_over_signals", read_signals)
    monkeypatch.setattr(bot, "_board_is_empty", board_empty)

    async def fake_dom(page):
        return dom_state

    monkeypatch.setattr(pe, "parse_state_from_dom", fake_dom)
    return bot


def state_with_full_row():
    wall = [[False] * 5 for _ in range(5)]
    wall[2] = [True] * 5
    return GameStateData(players=[PlayerState(index=0, name="Bot", wall=wall)])


def run(coro):
    return asyncio.run(coro)


def test_text_signal_alone_does_not_end_game(monkeypatch):
    # "no more turns remaining" in round 1-2 with an empty wall must be ignored
    bot = make_bot(monkeypatch, {"strong": False, "weak": True},
                   dom_state=GameStateData(players=[PlayerState(index=0, name="Bot")]))
    assert run(bot.check_game_over()) is False
    assert bot.game_over is False


def test_text_signal_with_completed_row_ends_game(monkeypatch):
    bot = make_bot(monkeypatch, {"strong": False, "weak": True}, dom_state=state_with_full_row())
    assert run(bot.check_game_over()) is True


def test_strong_signal_ends_game(monkeypatch):
    bot = make_bot(monkeypatch, {"strong": True, "weak": False})
    assert run(bot.check_game_over()) is True


def test_server_game_over_flag_wins(monkeypatch):
    bot = make_bot(monkeypatch)
    bot.game_over = True
    assert run(bot.check_game_over()) is True


def test_needs_deal_when_board_stays_empty(monkeypatch):
    bot = make_bot(monkeypatch, empty=[True, True])
    assert run(bot.needs_deal(settle_ms=1)) is True


def test_no_deal_if_board_refills_during_animation(monkeypatch):
    bot = make_bot(monkeypatch, empty=[True, False])
    assert run(bot.needs_deal(settle_ms=1)) is False


def test_no_deal_when_board_has_tiles(monkeypatch):
    bot = make_bot(monkeypatch, empty=[False])
    assert run(bot.needs_deal(settle_ms=1)) is False


def test_no_deal_once_game_is_over(monkeypatch):
    bot = make_bot(monkeypatch, empty=[True, True], signals={"strong": True, "weak": False})
    assert run(bot.needs_deal(settle_ms=1)) is False
