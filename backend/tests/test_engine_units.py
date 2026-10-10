"""Action executor, DOM/Socket.IO parsing, and BotBrowser/MultiPlayerSession with stub pages."""

import asyncio
import base64

import pytest

import app.engine.play_engine as pe
from app.engine import state_parser as sp
from app.engine.action_executor import (
    ExecutionResult, _build_choose_payload, _build_place_payload, _emit_and_wait, execute_action,
)
from app.models.schemas import (
    BrowserMode, DestinationType, GameAction, GameStateData, PlayerState, SourceType, TileColor,
)
from tests.fakes import FakeElement, FakePage, FakeSocketPage, instant_sleep


def run(c):
    return asyncio.run(c)


def action(src=SourceType.FACTORY, idx=2, dest=DestinationType.PATTERN_LINE, row=3):
    return GameAction(source_type=src, source_index=idx, color=TileColor.RED,
                      destination=dest, destination_row=row)


# ------------------------------------------------------------ action executor

def test_payload_builders():
    assert _build_choose_payload(action()) == {"turnType": "chooseTiles", "tileType": "red", "factory": "2"}
    assert _build_choose_payload(action(SourceType.CENTER, None))["center"] is True
    assert _build_place_payload(action())["patternLine"] == "3"
    assert _build_place_payload(action(dest=DestinationType.FLOOR, row=None))["floorLine"] is True


def test_execute_action_success():
    page = FakeSocketPage([{"ok": True}, {"ok": True}])
    res = run(execute_action(page, action()))
    assert res and not res.fell_back_to_floor
    assert [p["turnType"] for p in page.payloads] == ["chooseTiles", "placeTiles"]


def test_execute_action_choose_rejected():
    page = FakeSocketPage([{"ok": False, "msg": "not your turn"}])
    res = run(execute_action(page, action()))
    assert not res and isinstance(res, ExecutionResult)


def test_execute_action_pattern_line_rejected_falls_back_to_floor():
    page = FakeSocketPage([{"ok": True}, {"ok": False, "msg": "bad row"}, {"ok": True}])
    res = run(execute_action(page, action()))
    assert res and res.fell_back_to_floor
    assert page.payloads[-1]["floorLine"] is True


def test_execute_action_floor_fallback_also_rejected():
    page = FakeSocketPage([{"ok": True}, {"ok": False, "msg": "x"}, {"ok": False, "msg": "y"}])
    assert not run(execute_action(page, action()))


def test_execute_action_exception_returns_failure():
    class Boom(FakePage):
        async def evaluate(self, *_a, **_k):
            raise RuntimeError("page crashed")

    assert not run(execute_action(Boom(), action()))


def test_emit_and_wait_passes_payload_through():
    page = FakePage(routes=[("takeTurnResponse", {"ok": True, "msg": ""})])
    assert run(_emit_and_wait(page, {"turnType": "x"}))["ok"] is True


# ------------------------------------------------------------ socket.io parsing

def test_parse_helpers_cover_edge_cases():
    assert sp._safe_tile_color("firstPlayer") is None
    assert sp._safe_tile_color("purple") is None
    assert sp._safe_tile_color("red") == TileColor.RED
    assert sp._extract_tile_color({"type": "blue"}) == TileColor.BLUE
    assert sp._extract_tile_color("white") == TileColor.WHITE
    assert sp._extract_tile_color(42) is None
    assert sp._parse_pattern_lines("junk") == [[] for _ in range(5)]
    assert sp._parse_wall("junk") == [[False] * 5 for _ in range(5)]
    assert sp._parse_floor("junk") == []
    assert sp._parse_floor([{"color": "red"}, "blue", 7, {"type": "nope"}]) == [TileColor.RED, TileColor.BLUE]
    assert sp._parse_wall([[True, False], [{"selected": True}]])[0][0] is True
    assert sp._parse_pattern_lines([[{"selected": True, "color": "red"}, {"selected": False}]])[0] == [TileColor.RED]


def test_parse_game_object_center_and_dict_tiles():
    payload = {"success": True, "game": {
        "room": "r", "currentPlayer": "A", "round": 3, "gameOver": True,
        "factories": [[{"type": "red"}, "blue", {"color": "dummy"}]],
        "center": ["red", {"type": "blue"}, {"tileColor": "black"}, {"nothing": 1}],
        "players": {"A": {"score": 4, "floorLines": [{"color": "red"}], "hasFirstPlayerToken": True}},
    }}
    st = sp.parse_game_state_from_event(payload, "s1")
    assert st.game_over and st.round == 3
    assert st.factories == [[TileColor.RED, TileColor.BLUE]]
    assert st.center_pool == ["red", "blue", "black"]
    assert st.players[0].has_first_player_token and st.players[0].floor_line == [TileColor.RED]


def dom_result():
    wall = [[False] * 5 for _ in range(5)]
    wall[0][0] = True
    return {
        "factories": [["red", "red", "blue"], []],
        "center": ["yellow", "firstPlayer"],
        "players": [
            {"name": "Me", "score": 3, "patternLines": [["red"], [], [], [], []], "wall": wall, "floorLine": ["blue"]},
            {"name": "Opp", "score": 1, "patternLines": [[]], "wall": [[False] * 5] * 5, "floorLine": []},
        ],
    }


def test_parse_state_from_dom_converts_result():
    st = run(sp.parse_state_from_dom(FakePage(routes=[("factories", dom_result())])))
    assert [p.name for p in st.players] == ["Me", "Opp"]
    assert st.factories == [[TileColor.RED, TileColor.RED, TileColor.BLUE], []]
    assert st.players[0].pattern_lines[0] == [TileColor.RED]
    assert len(st.players[1].pattern_lines) == 5            # padded
    assert st.players[0].floor_line == [TileColor.BLUE]
    assert st.center_pool == ["yellow", "firstPlayer"]


def test_parse_state_from_dom_failure_returns_none():
    class Boom(FakePage):
        async def evaluate(self, *_a, **_k):
            raise RuntimeError("detached")

    assert run(sp.parse_state_from_dom(Boom())) is None


def test_parse_start_game_response_players():
    st = sp.parse_start_game_response(
        {"success": True, "players": [{"name": "A"}, {"patternLines": {}}]}, "room", "sid")
    assert [p.name for p in st.players] == ["A", "Player_1"]
    assert st.current_turn == "A"


# ------------------------------------------------------------ BotBrowser

def bot(**kw):
    return pe.BotBrowser("sid", "room", "Alice", **kw)


def test_launch_uses_headless_flag_and_base64_name(monkeypatch):
    page = FakePage()
    seen = {}

    class Ctx:
        async def new_page(self):
            return page

    class Browser:
        async def new_context(self, viewport=None):
            return Ctx()

    class Chromium:
        async def launch(self, headless):
            seen["headless"] = headless
            return Browser()

    class PW:
        chromium = Chromium()

    class Starter:
        async def start(self):
            return PW()

    monkeypatch.setattr(pe, "async_playwright", lambda: Starter())
    b = bot(browser_mode=BrowserMode.HEADED)
    run(b.launch())
    assert seen["headless"] is False
    assert page.url_visited.endswith("?name=" + base64.b64encode(b"Alice").decode())
    assert "websocket" in page.handlers and page.init_scripts
    assert b.page is page


def test_join_room_fills_and_clicks_and_detects_lobby():
    page = FakePage(routes=[("sharing-link-row", True)])
    b = bot()
    b._page = page
    run(b.join_room())
    assert page.selectors["#room"].filled == "room" and page.selectors["#start-game"].clicked == 1
    assert b.in_lobby


def test_join_room_requires_browser():
    with pytest.raises(RuntimeError):
        run(bot().join_room())


def test_start_game_host_clicks_enabled_button_and_waits_otherwise():
    page = FakePage(selectors={"#start-game-lobby": FakeElement({})})
    b = bot(is_host=True)
    b._page = page
    run(b.start_game())
    assert page.selectors["#start-game-lobby"].clicked == 1

    disabled = FakePage(selectors={"#start-game-lobby": FakeElement({"disabled": "true"})})
    b2 = bot(is_host=True)
    b2._page = disabled
    run(b2.start_game())                      # never enabled: gives up without clicking
    assert disabled.selectors["#start-game-lobby"].clicked == 0

    guest = bot(is_host=False)
    guest._page = page
    run(guest.start_game())


def test_deal_tiles_socket_and_fallback():
    b = bot()
    b._page = FakePage(routes=[("takeTurn", "socket")])
    assert run(b.deal_tiles(wait_s=0.01)) is True
    b2 = bot()
    b2._page = FakePage(routes=[("takeTurn", False), ("raw", False)])
    assert run(b2.deal_tiles()) is False
    assert run(bot().deal_tiles()) is False        # no page


def test_wait_for_state_update_times_out_or_succeeds():
    assert run(bot().wait_for_state_update(0.01)) is False
    b = bot()

    async def go():
        t = asyncio.create_task(b.wait_for_state_update(1))
        await asyncio.sleep(0.01)
        b._state_event.set()
        return await t

    assert run(go()) is True


def test_is_my_turn_from_state_then_dom():
    b = bot()
    b.current_state = GameStateData(current_turn="Alice")
    assert run(b.is_my_turn()) is True
    b.current_state = GameStateData(current_turn="Bob")
    assert run(b.is_my_turn()) is False
    b.current_state = None
    b._page = FakePage(routes=[("Select a tile", True)])
    assert run(b.is_my_turn()) is True
    assert run(bot().is_my_turn()) is False


def test_player_index_scores_and_execute(monkeypatch):
    b = bot()
    assert run(b.get_player_index()) == 0
    b.current_state = GameStateData(players=[PlayerState(index=0, name="Bob"), PlayerState(index=1, name="Alice")])
    assert run(b.get_player_index()) == 1
    b._page = FakePage(routes=[("player-", {"Alice": 5})])
    assert run(b.get_scores()) == {"Alice": 5}
    assert run(bot().get_scores()) == {}

    async def fake_exec(page, act, idx):
        return ExecutionResult(True)

    monkeypatch.setattr(pe, "execute_action", fake_exec)
    assert run(b.execute_move(action()))
    assert not run(bot().execute_move(action()))


def test_refresh_state_from_dom_stamps_session(monkeypatch):
    async def fake_parse(page):
        return GameStateData()

    monkeypatch.setattr(pe, "parse_state_from_dom", fake_parse)
    b = bot()
    b._page = FakePage()
    st = run(b.refresh_state_from_dom())
    assert st.session_id == "sid" and st.room_name == "room"
    assert run(bot().refresh_state_from_dom()) is None


def test_close_closes_page_and_survives_errors():
    b = bot()
    b._page = FakePage()
    run(b.close())
    assert b._page.closed

    class Bad:
        async def close(self):
            raise RuntimeError("already closed")

    b2 = bot()
    b2._page = Bad()
    run(b2.close())                              # must not raise


def frame(event, data):
    import json
    return "42" + json.dumps([event, data])


def test_websocket_frames_update_state():
    b = bot()
    game = {"success": True, "game": {"room": "r", "currentPlayer": "Alice", "gameOver": True,
                                      "factories": [], "center": [], "players": {}}}
    b._on_ws_frame(frame("takeTurnResponse", game), "received")
    assert b.game_started and b.game_over and b.current_state.current_turn == "Alice"
    assert b._state_event.is_set()

    b2 = bot()
    b2._on_ws_frame(frame("startGameResponse", {"success": True, "players": [{"name": "Alice"}]}), "received")
    assert b2.game_started
    b2._on_ws_frame(frame("joinRoomResponse", {"success": True}), "received")
    assert b2.in_lobby
    b2.game_started = False
    b2._on_ws_frame(frame("takeTurnResponse", game), "sent")     # outgoing frames are ignored
    b2._on_ws_frame("3probe", "received")
    assert b2.game_started is False
    b2._handle_websocket(type("W", (), {"on": lambda self, e, f: None})())


# ------------------------------------------------------------ MultiPlayerSession

def test_multiplayer_session_lifecycle(monkeypatch):
    mp = pe.MultiPlayerSession("sid", "room", "https://x", BrowserMode.HEADLESS)
    a = mp.add_bot("A", is_host=False)
    b = mp.add_bot("B", is_host=True)
    assert mp.host is b
    order = []

    async def mk(name, step):
        order.append((name, step))

    for bt in (a, b):
        monkeypatch.setattr(bt, "launch", lambda n=bt.player_name: mk(n, "launch"))
        monkeypatch.setattr(bt, "join_room", lambda n=bt.player_name: mk(n, "join"))
        monkeypatch.setattr(bt, "start_game", lambda n=bt.player_name: mk(n, "start"))
        monkeypatch.setattr(bt, "close", lambda n=bt.player_name: mk(n, "close"))

    async def fast(*_a):
        return None

    monkeypatch.setattr(pe.asyncio, "sleep", fast)
    a.lobby_players = b.lobby_players = {"A", "B"}
    run(mp.launch_all())
    run(mp.join_all())
    run(mp.start_game())
    run(mp.close_all())
    joins = [n for n, s in order if s == "join"]
    assert joins == ["B", "A"]                       # host creates the room first
    assert ("B", "start") in order and ("A", "start") not in order
    assert {n for n, s in order if s == "close"} == {"A", "B"}


def test_multiplayer_host_defaults_and_wait_for_humans(monkeypatch):
    mp = pe.MultiPlayerSession("sid", "room", "https://x", BrowserMode.HEADLESS)
    assert mp.host is None
    assert run(mp.wait_for_all_players(0.01)) is False
    first = mp.add_bot("A")
    assert mp.host is first
    run(mp.wait_for_humans())                        # no humans expected: returns immediately

    mp.human_count = 1
    monkeypatch.setattr(pe.asyncio, "sleep", instant_sleep)
    first.lobby_players = {"A"}
    run(mp.wait_for_humans(timeout_s=0.01))          # human never shows up: logs and returns
    first.lobby_players = {"A", "Human"}
    run(mp.wait_for_humans(timeout_s=5))             # roster complete


def test_start_game_refuses_to_start_short_handed(monkeypatch):
    mp = pe.MultiPlayerSession("sid", "room", "https://x", BrowserMode.HEADLESS)
    host = mp.add_bot("A", is_host=True)
    mp.add_bot("B")
    host.lobby_players = {"A"}                       # B never confirmed
    started = []

    async def fake_start():
        started.append(1)

    monkeypatch.setattr(host, "start_game", fake_start)
    with pytest.raises(RuntimeError, match="Only 1 of 2"):
        run(mp.start_game(join_timeout_s=0.01))
    assert started == []


def test_lobby_membership_tracked_from_platform_frames():
    import json as _json
    host = bot()
    host._on_ws_frame("42" + _json.dumps(["createRoomResponse", {"success": True, "players": []}]), "received")
    assert host.in_lobby and host.lobby_players == {"Alice"}
    host._on_ws_frame(_json.dumps({"type": "joinRoomResponse", "payload": {"success": True, "players": ["Bob"]}}), "received")
    host._on_ws_frame(_json.dumps({"type": "joinRoomResponse", "payload": {"success": False, "players": ["Zed"]}}), "received")
    assert host.lobby_players == {"Alice", "Bob"}


def test_join_room_retries_then_fails_loudly(monkeypatch):
    b = bot()
    b._page = FakePage()                              # lobby never appears
    monkeypatch.setattr(pe.asyncio, "sleep", instant_sleep)

    async def never(timeout_s):
        return False

    monkeypatch.setattr(b, "_wait_in_lobby", never)
    with pytest.raises(RuntimeError, match="could not join"):
        run(b.join_room(attempts=2))
    assert b._page.selectors["#start-game"].clicked == 2


def test_join_room_confirmed_by_platform_event():
    b = bot()
    b._page = FakePage()
    b.in_lobby = True                                 # createRoomResponse/joinRoomResponse arrived
    run(b.join_room())
    assert b._page.selectors["#start-game"].clicked == 1


def test_wait_in_lobby_times_out_without_confirmation(monkeypatch):
    b = bot()
    b._page = FakePage(routes=[("sharing-link-row", False)])
    assert run(b._wait_in_lobby(0.05)) is False


def test_page_load_retries_then_succeeds(monkeypatch):
    class Flaky(FakePage):
        attempts = 0

        async def goto(self, url, wait_until=None, timeout=None):
            Flaky.attempts += 1
            if Flaky.attempts < 3:
                raise TimeoutError("Page.goto: Timeout 45000ms exceeded")
            self.url_visited = url

    monkeypatch.setattr(pe.asyncio, "sleep", instant_sleep)
    b = bot()
    b._page = Flaky()
    run(b._open_with_retries("https://x"))
    assert Flaky.attempts == 3 and b._page.url_visited == "https://x"


def test_page_load_gives_up_after_all_attempts(monkeypatch):
    class Dead(FakePage):
        async def goto(self, *a, **k):
            raise TimeoutError("down")

    monkeypatch.setattr(pe.asyncio, "sleep", instant_sleep)
    b = bot()
    b._page = Dead()
    with pytest.raises(TimeoutError):
        run(b._open_with_retries("https://x", attempts=2))
