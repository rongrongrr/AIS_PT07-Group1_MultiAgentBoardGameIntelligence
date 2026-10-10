"""Live-play loop tests without a browser.

``FakeSite`` stands in for buddyboardgames.com: it owns the authoritative
game, validates ``takeTurn`` payloads with the real rules engine, leaves
the table empty at round boundaries until a ``dealTiles`` arrives (like
the real platform), and broadcasts the site-shaped ``game`` object to
every seat. ``FakeSeat`` implements the ``BrowserSeat`` surface on top of
it. This exercises everything in ``LiveSession`` except Playwright:
joining, the opening deal, the propose → emit → conclude turn, round
transitions, opponent-move inference for human seats, stopping, and the
ledger/event contract.
"""

from __future__ import annotations

import asyncio
import random
import threading
import time

import pytest

from tiles.agents.explainer import TemplateExplainer
from tiles.agents.profiler import BasicProfiler
from tiles.agents.tacticians.greedy import GreedyTactician
from tiles.agents.tacticians.random_tactician import RandomTactician
from tiles.core import (
    CENTER,
    FLOOR,
    Action,
    check_action,
    color_from_name,
    deal_round,
    legal_actions,
    new_game,
    step,
)
from tiles.engine.live_session import LiveSeat, LiveSession, LiveSessionConfig
from tiles.engine.state_translator import game_state_to_site_game
from tiles.ledger import Ledger


class FakeSite:
    """The 'server': authoritative state + takeTurn protocol."""

    def __init__(self, names, seed=0, auto_deal=False):
        self.state = new_game(len(names), seed=seed, player_names=names)
        self.rng = random.Random(seed)
        self.seats = []
        self.humans = []
        self.started = False
        self.auto_deal = auto_deal
        self.busy_rooms = set()  # names the 'platform' refuses
        self.needs_deal = False  # new_game already dealt round 1
        self.turns = 0

    def join(self, seat):
        self.seats.append(seat)

    def start(self):
        self.started = True
        for seat in self.seats:
            seat.site_players = [p.name for p in self.state.players]
        if self.auto_deal:
            self.broadcast()

    def broadcast(self):
        game = game_state_to_site_game(self.state, room="fake")
        game["round"] = self.state.round_number
        for seat in self.seats:
            seat._receive(dict(game))

    @staticmethod
    def _action(choose, place):
        source = CENTER if choose.get("center") else int(choose["factory"])
        color = color_from_name(choose["tileType"])
        dest = FLOOR if place.get("floorLine") else int(place["patternLine"])
        return Action(source, color, dest)

    def take_turn(self, player, choose, place):
        if self.needs_deal:
            return {"ok": False, "msg": "deal first"}
        current = self.state.players[self.state.current_player].name
        if current != player:
            return {"ok": False, "msg": f"not your turn ({current})"}
        action = self._action(choose, place)
        violation = check_action(self.state, action)
        if violation is not None:
            return {"ok": False, "msg": violation.message}
        _, round_result = step(self.state, action)
        self.turns += 1
        if round_result is not None and not round_result.game_over:
            self.needs_deal = True
        self.broadcast()
        return {"ok": True, "msg": ""}

    def deal(self):
        if self.needs_deal:
            deal_round(self.state, self.rng)
            self.needs_deal = False
        self.broadcast()


class FakeSeat:
    def __init__(self, site, room_name, player_name, platform_url, headless, is_host):
        self.site = site
        self.room_name = room_name
        self.player_name = player_name
        self.is_host = is_host
        self.site_game = None
        self.site_players = []
        self.lobby_players = []
        self.state_seq = 0
        self.rounds_dealt = 0
        self.game_over = False
        self.closed = False
        self._event = asyncio.Event()

    # lifecycle
    async def launch(self):
        pass

    async def join_room(self):
        if self.room_name in self.site.busy_rooms:
            raise RuntimeError(
                f"{self.player_name} could not join room {self.room_name!r}: "
                "This room name is already in use by a game in progress."
            )
        self.site.join(self)

    async def start_game(self):
        if not self.is_host:
            return False
        self.site.start()
        return True

    async def close(self):
        self.closed = True

    # state
    def _receive(self, game):
        self.site_game = game
        self.state_seq += 1
        self.rounds_dealt = int(game.get("round", 1))
        if game.get("gameOver"):
            self.game_over = True
        self._event.set()

    async def wait_for_state(self, timeout_s=10, since=None):
        if since is not None and self.state_seq > since:
            return True
        self._event.clear()
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout_s)
            return True
        except asyncio.TimeoutError:
            return False

    async def needs_deal(self):
        return self.site.needs_deal

    async def check_game_over(self):
        return self.game_over or self.site.state.is_game_over

    async def lobby_player_count(self):
        return len(self.site.seats) + len(self.site.humans)

    async def dom_snapshot(self):
        return None

    # actions
    async def emit_action(self, choose, place):
        result = self.site.take_turn(self.player_name, choose, place)
        return {"ok": result["ok"], "msg": result["msg"], "fallback": False}

    async def deal_tiles(self):
        self.site.deal()
        return True


def fast_config(seats, **overrides):
    config = LiveSessionConfig(
        room_name="fake-room",
        seats=seats,
        poll_interval_s=0.01,
        deal_timeout_s=0.05,
        deal_grace_s=0.02,
        state_timeout_s=1.0,
        turn_timeout_s=1.0,
        human_join_timeout_s=0.5,
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def run_session(site, config, **kwargs):
    events = []
    session = LiveSession(
        config,
        on_event=events.append,
        seat_factory=lambda **kw: FakeSeat(site, **kw),
        **kwargs,
    )
    result = asyncio.run(session.run())
    return session, result, events


# ---------------------------------------------------------------------------
# Full bot-vs-bot game, host must deal because the site stays silent
# ---------------------------------------------------------------------------


def test_full_live_game_records_contract_shaped_moves(tmp_path):
    site = FakeSite(["Alpha", "Beta"], seed=3)
    ledger = Ledger(tmp_path / "live.db")
    ledger.create_session("sess_live", mode="live")
    seats = [
        LiveSeat("Alpha", GreedyTactician()),
        LiveSeat("Beta", RandomTactician(seed=1)),
    ]
    session, result, events = run_session(
        site,
        fast_config(seats),
        profiler=BasicProfiler(),
        explainer=TemplateExplainer(),
        ledger=ledger,
        session_id="sess_live",
    )

    assert result["status"] == "completed"
    assert site.state.is_game_over
    assert result["steps"] == site.turns > 10
    assert result["scores"] == site.state.scores()
    assert result["winner_name"] in ("Alpha", "Beta")

    statuses = [e["status"] for e in events if e["type"] == "status"]
    assert statuses[:3] == ["connecting", "lobby", "running"]
    first_status = next(e for e in events if e["type"] == "status")
    assert first_status["room_name"] == "fake-room"
    assert "?room=" in first_status["room_url"] and "fake-room" not in first_status["room_url"]
    types = {e["type"] for e in events}
    assert {"move", "state", "round", "game_over", "log"} <= types
    # the "host emits dealTiles" fallback fired (site was silent on start)
    assert any("dealTiles" in e.get("message", "") for e in events if e["type"] == "log")

    moves = [e["record"] for e in events if e["type"] == "move"]
    assert [m["step"] for m in moves] == list(range(1, len(moves) + 1))
    for record in moves:
        assert record["validation"]["ok"] is True
        assert record["validation"]["site_fallback"] is False
        assert "execute_ms" in record["timing"] and "decide_ms" in record["timing"]
        assert record["explanation"]["text"]
        assert record["state_before"]["players"][record["player_index"]]["name"] == record["player_name"]
        assert record["state_after"] is not None
    # rounds were reported as the site advanced them
    rounds = [e["round"] for e in events if e["type"] == "round"]
    assert rounds == sorted(rounds) and rounds[0] == 1

    # ledger mirrors the stream
    assert len(ledger.get_history("sess_live")) == len(moves)
    stored = ledger.get_session("sess_live")
    assert stored["status"] == "completed"
    assert stored["result"]["scores"] == result["scores"]
    assert len(ledger.get_profiles("sess_live")) == 2
    assert len(ledger.get_rounds("sess_live")) == len(rounds)
    assert all(seat.closed for seat in session.seats.values())
    ledger.close()


def test_auto_deal_path_skips_manual_deal():
    site = FakeSite(["Alpha", "Beta"], seed=5, auto_deal=True)
    seats = [LiveSeat("Alpha", GreedyTactician()), LiveSeat("Beta", GreedyTactician())]
    _, result, events = run_session(site, fast_config(seats))
    assert result["status"] == "completed"
    assert not any(
        "dealTiles" in e.get("message", "") for e in events if e["type"] == "log"
    )


# ---------------------------------------------------------------------------
# Human seat: the loop waits, infers the human's moves, records and profiles them
# ---------------------------------------------------------------------------


def test_human_seat_moves_are_inferred_recorded_and_profiled(tmp_path):
    site = FakeSite(["Bot", "Human"], seed=11, auto_deal=True)
    site.humans.append("Human")
    human_brain = GreedyTactician()
    seats = [LiveSeat("Bot", GreedyTactician()), LiveSeat("Human", None)]
    profiler = BasicProfiler()
    ledger = Ledger(tmp_path / "human.db")
    ledger.create_session("sess_human", mode="live")
    events = []
    stop = threading.Event()
    human_turns = []

    async def play_human():
        # Acts like the human's own browser: moves when it is their turn.
        while not site.state.is_game_over and not stop.is_set():
            if site.started and not site.needs_deal and \
                    site.state.players[site.state.current_player].name == "Human":
                legal = legal_actions(site.state)
                from tiles.agents.base import DecisionContext

                decision = human_brain.decide(
                    DecisionContext(site.state, site.state.current_player, legal)
                )
                from tiles.engine.state_translator import action_to_site_moves

                choose, place = action_to_site_moves(decision.action)
                if site.take_turn("Human", choose, place)["ok"]:
                    human_turns.append(decision.action)
            elif site.started and site.needs_deal and \
                    site.state.players[site.state.current_player].name == "Human":
                site.deal()
            await asyncio.sleep(0.005)

    async def main():
        session = LiveSession(
            fast_config(seats),
            on_event=events.append,
            profiler=profiler,
            ledger=ledger,
            session_id="sess_human",
            seat_factory=lambda **kw: FakeSeat(site, **kw),
        )
        human_task = asyncio.create_task(play_human())
        try:
            return await session.run()
        finally:
            stop.set()
            human_task.cancel()

    result = asyncio.run(main())
    assert result["status"] == "completed"
    lobby = [e for e in events if e["type"] == "status" and e["status"] == "lobby"][0]
    assert lobby["waiting_for_humans"] == ["Human"]
    records = [e["record"] for e in events if e["type"] == "move"]
    bot_moves = [r for r in records if r["player_name"] == "Bot"]
    human_moves = [r for r in records if r["player_name"] == "Human"]
    # Every human move -- including round- and game-ending ones -- is
    # recorded with the action actually played, in step order.
    assert [r["step"] for r in records] == list(range(1, len(records) + 1))
    assert [Action.from_dict(r["action"]) for r in human_moves] == human_turns
    assert len(bot_moves) + len(human_moves) == site.turns
    for r in human_moves:
        assert r["tactician"] == "human"
        assert r["validation"]["inferred"] is True
        assert r["explanation"] is None
        assert r["state_before"]["players"][r["player_index"]]["name"] == "Human"
    human_index = [p.name for p in site.state.players].index("Human")
    assert profiler.profile(human_index).moves_observed == len(human_moves)
    assert profiler.profile(1 - human_index).moves_observed == len(bot_moves)
    # The ledger holds both seats, so post-hoc profiling sees the human.
    history = ledger.get_history("sess_human")
    assert len(history) == len(records)
    assert {r["player_name"] for r in history} == {"Bot", "Human"}
    ledger.close()


# ---------------------------------------------------------------------------
# Stop + failure handling
# ---------------------------------------------------------------------------


def test_stop_event_aborts_the_game():
    site = FakeSite(["Alpha", "Beta"], seed=2, auto_deal=True)
    stop_event = threading.Event()
    events = []

    def on_event(event):
        events.append(event)
        if event["type"] == "move" and event["step"] >= 3:
            stop_event.set()

    config = fast_config(
        [LiveSeat("Alpha", GreedyTactician()), LiveSeat("Beta", GreedyTactician())]
    )
    session = LiveSession(
        config,
        on_event=on_event,
        stop_event=stop_event,
        seat_factory=lambda **kw: FakeSeat(site, **kw),
    )
    result = asyncio.run(session.run())
    assert result["status"] == "aborted"
    assert 3 <= result["steps"] <= 5
    assert events[-1]["type"] == "status" and events[-1]["status"] == "aborted"


def test_stop_interrupts_a_long_wait_on_a_human():
    site = FakeSite(["Bot", "Human"], seed=4, auto_deal=True)
    site.humans.append("Human")  # in the lobby, but never moves
    stop_event = threading.Event()
    config = fast_config(
        [LiveSeat("Bot", GreedyTactician()), LiveSeat("Human", None)],
        turn_timeout_s=60.0,
    )
    session = LiveSession(
        config,
        stop_event=stop_event,
        seat_factory=lambda **kw: FakeSeat(site, **kw),
    )
    threading.Timer(0.5, stop_event.set).start()
    t0 = time.monotonic()
    result = asyncio.run(session.run())
    assert result["status"] == "aborted"
    assert time.monotonic() - t0 < 5
    assert all(seat.closed for seat in session.seats.values())


def test_persistent_rejection_raises():
    site = FakeSite(["Alpha", "Beta"], seed=2, auto_deal=True)

    class RejectingSeat(FakeSeat):
        async def emit_action(self, choose, place):
            return {"ok": False, "msg": "nope", "fallback": False}

    config = fast_config(
        [LiveSeat("Alpha", GreedyTactician()), LiveSeat("Beta", GreedyTactician())],
        state_timeout_s=0.01,
    )
    session = LiveSession(
        config, seat_factory=lambda **kw: RejectingSeat(site, **kw)
    )
    with pytest.raises(RuntimeError, match="rejected"):
        asyncio.run(session.run())


def test_needs_a_bot_seat():
    config = fast_config([LiveSeat("A", None), LiveSeat("B", None)])
    with pytest.raises(ValueError):
        asyncio.run(LiveSession(config, seat_factory=lambda **kw: None).run())


def test_room_name_collision_retries_under_a_fresh_name():
    site = FakeSite(["Alpha", "Beta"], seed=4, auto_deal=True)
    site.busy_rooms.add("fake-room")
    seats = [LiveSeat("Alpha", GreedyTactician()), LiveSeat("Beta", GreedyTactician())]
    session, result, events = run_session(site, fast_config(seats))
    assert result["status"] == "completed"
    assert session.config.room_name != "fake-room"
    assert session.config.room_name.startswith("fake-room-")
    assert all(seat.room_name == session.config.room_name for seat in session.seats.values())
    warnings = [e for e in events if e["type"] == "log" and e["level"] == "warning"]
    assert any("still in use" in e["message"] for e in warnings)
    statuses = [e for e in events if e["type"] == "status"]
    assert statuses[-1]["room_name"] == session.config.room_name


def test_persistent_room_collision_fails_clearly():
    site = FakeSite(["Alpha", "Beta"], seed=4, auto_deal=True)

    class AlwaysBusySeat(FakeSeat):
        async def join_room(self):
            raise RuntimeError("could not join: This room name is already in use by a game in progress.")

    config = fast_config([LiveSeat("Alpha", GreedyTactician()), LiveSeat("Beta", GreedyTactician())])
    with pytest.raises(RuntimeError, match="already in use"):
        asyncio.run(LiveSession(config, seat_factory=lambda **kw: AlwaysBusySeat(site, **kw)).run())
