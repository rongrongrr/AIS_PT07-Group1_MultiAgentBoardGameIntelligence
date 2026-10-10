"""The real game-orchestration loop (sessions._run_multi_bot_game) against a fake platform.

The fake platform is the simulation engine, so these tests play complete multi-round
games through the production code path (state read, decide, validate, execute, verify,
ledger, broadcast) with no browser or network.
"""

import asyncio
import json

import pytest

from tiles.azul.rules import is_game_over
from tiles.ml.base import MachinePlayer
from tiles.ml.registry import registry
from tiles.models.db import GameState, Move, Session
from tiles.models.schemas import DestinationType, GameAction, SourceType, TileColor
from tiles.routers import sessions as S
from tests.fakes import FakeBot, FakeClock, FakeMP, FakePlatform, instant_sleep

NAMES = ["Alice", "Bob"]


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(S.asyncio, "sleep", instant_sleep)


def make_session(db, sid="sess_test", players=None):
    row = Session(
        id=sid, room_name="fake-room", platform_url="https://buddyboardgames.com/azul",
        browser_mode="headless", status="created",
        player_config=json.dumps(players or [{"slot": 0, "type": "GreedyPlayer", "name": "Alice"},
                                             {"slot": 1, "type": "GreedyPlayer", "name": "Bob"}]),
        move_timeout_sec=5, stuck_abort_sec=2,
    )
    db.add(row)
    db.commit()
    return row


def setup(db, models=("GreedyPlayer", "RandomPlayer"), seed=1, **bot_kw):
    platform = FakePlatform(NAMES, seed=seed)
    bots = [FakeBot(platform, n, is_host=(i == 0), **(bot_kw if i == 0 else {})) for i, n in enumerate(NAMES)]
    mp = FakeMP(platform, bots)
    bot_models = {n: registry.create_player(m) for n, m in zip(NAMES, models)}
    make_session(db)
    return platform, mp, bot_models


def run_game(db, mp, bot_models, **kw):
    asyncio.run(S._run_multi_bot_game("sess_test", mp, bot_models, db,
                                      move_timeout_sec=kw.pop("move_timeout_sec", 5),
                                      stuck_abort_sec=kw.pop("stuck_abort_sec", 2)))
    db.expire_all()
    return db.query(Session).filter(Session.id == "sess_test").first()


class BadModel(MachinePlayer):
    """Proposes an action that is never legal."""

    @property
    def name(self):
        return "BadModel"

    async def decide(self, game_state, player_index):
        return GameAction(source_type=SourceType.FACTORY, source_index=99, color=TileColor.RED,
                          destination=DestinationType.FLOOR)


class CrashModel(BadModel):
    async def decide(self, game_state, player_index):
        raise RuntimeError("boom")


class HangModel(BadModel):
    async def decide(self, game_state, player_index):
        await asyncio.Event().wait()


def test_full_multi_round_game_completes_and_is_recorded(db):
    platform, mp, models = setup(db)
    row = run_game(db, mp, models)

    sim = platform.sim
    assert sim.finished and is_game_over(sim.state)
    assert sim.state.round >= 5                      # a real game spans several rounds
    assert row.status == "completed"
    assert row.winner in NAMES
    assert set(json.loads(row.final_scores)) == set(NAMES)
    assert mp.closed

    moves = db.query(Move).filter(Move.session_id == "sess_test").order_by(Move.step_id).all()
    assert len(moves) == platform.moves_applied
    assert [m.step_id for m in moves] == list(range(1, len(moves) + 1))
    extra = json.loads(moves[0].action_json)["_extra"]
    for key in ("board", "scores", "click_ms", "total_ms", "legal_actions", "explanation"):
        assert key in extra
    assert extra["explanation"]["top_alternatives"]            # "why this move" is persisted

    # each state snapshot is stored under the id of the move that follows it
    snaps = {g.step_id for g in db.query(GameState).filter(GameState.session_id == "sess_test")}
    assert set(range(1, len(moves) + 1)) <= snaps


def test_both_players_get_independent_model_state(db):
    platform, mp, models = setup(db, models=("AdaptivePlayer", "GreedyPlayer"))
    run_game(db, mp, models)
    adaptive = models["Alice"]
    assert list(adaptive.history) == ["Bob"]                   # observed only the opponent
    assert len(adaptive.history["Bob"]) > 10


def test_floor_fallback_is_recorded_as_played(db):
    platform, mp, models = setup(db, fallback_first=True)
    run_game(db, mp, models)
    first = db.query(Move).filter(Move.session_id == "sess_test", Move.step_id == 1).first()
    data = json.loads(first.action_json)
    assert data["destination"] == "floor"
    assert data["_extra"]["fell_back_to_floor"] is True


def test_failed_clicks_are_retried(db):
    platform, mp, models = setup(db, fail_first=2)
    row = run_game(db, mp, models)
    assert row.status == "completed"


def test_dom_only_confirmation_path(db):
    platform, mp, models = setup(db, ws_updates=False)
    row = run_game(db, mp, models)
    assert row.status == "completed"


def test_initial_deal_when_no_tiles_present(db):
    platform, mp, models = setup(db)
    platform.sim.state.factories = [[] for _ in platform.sim.state.factories]
    platform.sim.state.center_pool = []
    row = run_game(db, mp, models)
    assert mp.bots[0].deals >= 1
    assert row.status == "completed"


def test_illegal_model_move_is_rejected_then_session_aborts(db, monkeypatch):
    platform, mp, models = setup(db, models=("GreedyPlayer", "GreedyPlayer"))
    models["Alice"] = BadModel()
    models["Bob"] = BadModel()
    monkeypatch.setattr(S, "time", FakeClock())
    row = run_game(db, mp, models)
    assert platform.moves_applied == 0
    assert row.status == "aborted"


def test_model_exception_aborts_stuck_session(db, monkeypatch):
    platform, mp, models = setup(db)
    models["Alice"] = CrashModel()
    models["Bob"] = CrashModel()
    monkeypatch.setattr(S, "time", FakeClock())
    assert run_game(db, mp, models).status == "aborted"


def test_model_timeout_is_handled(db, monkeypatch):
    platform, mp, models = setup(db)
    models["Alice"] = HangModel()
    models["Bob"] = HangModel()
    monkeypatch.setattr(S, "time", FakeClock())
    assert run_game(db, mp, models, move_timeout_sec=1).status == "aborted"


def test_move_with_no_effect_is_not_recorded(db, monkeypatch):
    platform, mp, models = setup(db, ignore_moves=True, ws_updates=False)
    mp.bots[1].ignore_moves = True
    mp.bots[1].ws_updates = False
    monkeypatch.setattr(S, "time", FakeClock())
    row = run_game(db, mp, models)
    assert db.query(Move).filter(Move.session_id == "sess_test").count() == 0
    assert row.status == "aborted"


def test_launch_failure_marks_session_aborted(db):
    platform, mp, models = setup(db)
    mp.launch_error = RuntimeError("no browser")
    row = run_game(db, mp, models)
    assert row.status == "aborted"
    assert mp.closed


def test_humans_are_awaited_and_do_not_trigger_stuck_abort(db, monkeypatch):
    platform, mp, models = setup(db)
    mp.human_count = 1
    row = run_game(db, mp, models)
    assert mp.humans_waited
    assert row.status == "completed"


def test_game_that_ends_without_a_full_wall_row_is_not_completed(db):
    platform, mp, models = setup(db)

    class EarlyOver(FakeBot):
        async def check_game_over(self):          # claims the game is over immediately
            self.game_over = True
            return True

    mp.bots = [EarlyOver(platform, n, is_host=(i == 0)) for i, n in enumerate(NAMES)]
    row = run_game(db, mp, models)
    assert row.status == "aborted"


def test_cancellation_is_clean(db):
    platform, mp, models = setup(db)
    models["Alice"] = HangModel()
    models["Bob"] = HangModel()

    async def go():
        task = asyncio.create_task(S._run_multi_bot_game("sess_test", mp, models, db, 60, 60))
        for _ in range(50):
            await asyncio.sleep(0)
        task.cancel()
        await task

    asyncio.run(go())
    assert mp.closed


def test_update_status_picks_highest_score_as_winner(db):
    make_session(db)
    S._update_db_status("sess_test", S.SessionStatus.COMPLETED, db, scores={"A": 3, "B": 9})
    row = db.query(Session).first()
    assert row.winner == "B" and row.completed_at is not None


def test_states_equal_helper():
    from tiles.models.schemas import GameStateData
    a = GameStateData(factories=[[TileColor.RED]])
    assert S._states_equal(a, a.model_copy(deep=True))
    assert not S._states_equal(a, GameStateData(factories=[[TileColor.BLUE]]))
    assert S._states_equal(None, None) and not S._states_equal(a, None)


class BotWithHumanOpponent(FakeBot):
    """A bot whose room also holds a human: the human thinks for one poll, then plays a random legal move."""

    def __init__(self, platform, name, human_seat, **kw):
        super().__init__(platform, name, **kw)
        self.human_seat = human_seat
        self.polls = 0
        self.rng = __import__("random").Random(2)
        self.human_moves = 0
        self.mute = False                                       # a human who never moves

    def _view(self):
        s = super()._view()
        s.current_turn = self.platform.sim.state.current_turn
        return s

    async def is_my_turn(self):
        from tiles.azul.game import apply_action, round_over, step_round_boundary
        from tiles.azul.rules import get_legal_actions
        sim = self.platform.sim
        if not sim.finished and round_over(sim.state):
            step_round_boundary(sim)                            # the site deals the next round by itself
        if not sim.finished and sim.current == self.human_seat:
            self.current_state = self._view()
            self.polls += 1
            if self.polls % 2 == 0 and not self.mute:
                apply_action(sim, self.rng.choice(get_legal_actions(sim.state, sim.current)))
                self.human_moves += 1
                self.current_state = self._view()
            return False
        return await super().is_my_turn()


def test_human_moves_are_inferred_and_recorded(db):
    platform = FakePlatform(NAMES, seed=3)
    bot = BotWithHumanOpponent(platform, "Alice", human_seat=1, is_host=True)
    mp = FakeMP(platform, [bot], human_count=1)
    make_session(db, players=[{"slot": 0, "type": "GreedyPlayer", "name": "Alice"}, {"slot": 1, "type": "human", "name": "Bob"}])
    models = {"Alice": registry.create_player("AdaptivePlayer")}
    row = run_game(db, mp, models)
    assert mp.humans_waited and row.status == "completed"

    moves = db.query(Move).filter(Move.session_id == "sess_test").order_by(Move.step_id).all()
    human = [m for m in moves if m.player_name == "Bob"]
    assert len(human) >= bot.human_moves - 1                    # at most the unobservable final move is missing
    assert all(m.system_tag == "human" for m in human)
    assert [m.step_id for m in moves] == list(range(1, len(moves) + 1))
    assert json.loads(human[0].action_json)["_extra"]["inferred"] is True
    assert list(models["Alice"].history) == ["Bob"]             # the adaptive bot modelled the human's moves
    assert len(models["Alice"].history["Bob"]) == len(human)
