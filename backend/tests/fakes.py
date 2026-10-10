"""Test doubles: a scriptable page and a fake Azul platform driven by the simulation engine."""

from __future__ import annotations

import asyncio
from typing import Any, List, Optional, Tuple

from tiles.azul.game import apply_action, new_game, round_over, step_round_boundary
from tiles.engine.action_executor import ExecutionResult
from tiles.models.schemas import DestinationType, GameAction


class FakeElement:
    def __init__(self, attrs: Optional[dict] = None):
        self.attrs = attrs or {}
        self.clicked = 0
        self.filled: Optional[str] = None

    async def get_attribute(self, name):
        return self.attrs.get(name)

    async def click(self):
        self.clicked += 1

    async def fill(self, text):
        self.filled = text


class FakePage:
    """Playwright Page stand-in. ``routes`` maps a substring of the evaluated JS to a result
    (or a callable taking the argument); results given as a list are consumed in order."""

    def __init__(self, routes: Optional[List[Tuple[str, Any]]] = None, selectors: Optional[dict] = None):
        self.routes = routes or []
        self.selectors = selectors or {}
        self.calls: List[Tuple[str, Any]] = []
        self.handlers = {}
        self.init_scripts: List[str] = []
        self.closed = False
        self.url_visited: Optional[str] = None

    async def evaluate(self, script, arg=None):
        self.calls.append((script, arg))
        for key, result in self.routes:
            if key in script:
                if isinstance(result, list):
                    return result.pop(0) if result else None
                if callable(result):
                    return result(arg)
                if isinstance(result, Exception):
                    raise result
                return result
        return None

    async def wait_for_timeout(self, ms):
        return None

    async def wait_for_selector(self, sel, timeout=None):
        return self.selectors.setdefault(sel, FakeElement())

    async def query_selector(self, sel):
        return self.selectors.get(sel)

    async def goto(self, url, wait_until=None, timeout=None):
        self.url_visited = url

    async def wait_for_load_state(self, state=None, timeout=None):
        return None

    async def is_visible(self, sel):
        return True

    async def add_init_script(self, script):
        self.init_scripts.append(script)

    def on(self, event, handler):
        self.handlers[event] = handler

    async def close(self):
        self.closed = True


class FakeSocketPage(FakePage):
    """Page whose evaluate() answers emit-and-wait calls from a queue of {ok, msg} dicts."""

    def __init__(self, responses: List[dict]):
        super().__init__()
        self.responses = list(responses)
        self.payloads: List[dict] = []

    async def evaluate(self, script, arg=None):
        self.payloads.append(arg)
        return self.responses.pop(0) if self.responses else {"ok": True, "msg": ""}


# ---------------------------------------------------------------- fake platform

class FakePlatform:
    """An Azul 'website' backed by the simulation engine, seen from each bot's DOM perspective."""

    def __init__(self, names: List[str], seed: int = 1):
        self.names = names
        self.sim = new_game(names, seed)
        self.moves_applied = 0


class FakeBot:
    """Quacks like BotBrowser for the orchestration loop."""

    def __init__(self, platform: FakePlatform, name: str, is_host: bool = False,
                 ws_updates: bool = True, fail_first: int = 0, fallback_first: bool = False,
                 ignore_moves: bool = False):
        self.platform = platform
        self.player_name = name
        self.seat = platform.names.index(name)
        self.is_host = is_host
        self.game_over = False
        self.game_started = False
        self.current_state = None
        self.ws_state = None
        self.page = object()
        self.ws_updates = ws_updates
        self.fail_first = fail_first
        self.fallback_first = fallback_first
        self.ignore_moves = ignore_moves
        self.deals = 0

    def _view(self):
        s = self.platform.sim.state.model_copy(deep=True)
        n = len(s.players)
        order = [s.players[(self.seat + i) % n] for i in range(n)]
        for i, p in enumerate(order):
            p.index = i
        s.players = order
        s.current_turn = ""
        s.session_id = "sess"
        s.round = 1  # like the real DOM parser, which does not read the round
        return s

    async def refresh_state_from_dom(self):
        self.current_state = self._view()
        return self.current_state

    async def is_my_turn(self):
        sim = self.platform.sim
        return not sim.finished and sim.current == self.seat

    async def needs_deal(self):
        sim = self.platform.sim
        return not sim.finished and round_over(sim.state)

    async def deal_tiles(self):
        self.deals += 1
        step_round_boundary(self.platform.sim)
        return True

    def arm_state_event(self):
        return None

    async def wait_for_state_update(self, timeout_s=0, clear=True):
        return self.ws_updates

    async def check_game_over(self):
        if self.platform.sim.finished:
            self.game_over = True
        return self.game_over

    async def get_player_index(self):
        if self.current_state:
            for p in self.current_state.players:
                if p.name == self.player_name:
                    return p.index
        return 0

    async def execute_move(self, action: GameAction):
        if self.fail_first > 0:
            self.fail_first -= 1
            return ExecutionResult(False)
        if self.ignore_moves:
            return ExecutionResult(True)  # claims success but the board does not change
        fell_back = False
        if self.fallback_first:
            self.fallback_first = False
            fell_back = True
            action = GameAction(source_type=action.source_type, source_index=action.source_index,
                                color=action.color, destination=DestinationType.FLOOR)
        apply_action(self.platform.sim, action)
        self.platform.moves_applied += 1
        return ExecutionResult(True, fell_back)

    async def get_scores(self):
        return {p.name: p.score for p in self.platform.sim.state.players}

    async def close(self):
        return None


class FakeMP:
    """Stand-in for MultiPlayerSession."""

    def __init__(self, platform: FakePlatform, bots: List[FakeBot], human_count: int = 0,
                 launch_error: Optional[Exception] = None):
        self.platform = platform
        self.bots = bots
        self.human_count = human_count
        self.room_name = "fake-room"
        self.launch_error = launch_error
        self.humans_waited = False
        self.closed = False

    @property
    def host(self):
        return next((b for b in self.bots if b.is_host), self.bots[0])

    async def launch_all(self):
        if self.launch_error:
            raise self.launch_error

    async def join_all(self):
        return None

    async def wait_for_humans(self, timeout_s=300):
        self.humans_waited = True

    async def start_game(self):
        for b in self.bots:
            b.game_started = True

    async def close_all(self):
        self.closed = True


class FakeClock:
    """Advances 0.5s per call so stuck/timeout logic triggers without real waiting."""

    def __init__(self):
        self.t = 1_000.0

    def time(self):
        self.t += 0.5
        return self.t


_REAL_SLEEP = asyncio.sleep


async def instant_sleep(*_a, **_k):
    await _REAL_SLEEP(0)
