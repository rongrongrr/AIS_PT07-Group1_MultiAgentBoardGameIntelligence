"""Turn pipeline + match runner tests."""

from tiles.agents.base import Decision, DecisionContext, Tactician
from tiles.agents.tacticians.greedy import GreedyTactician
from tiles.agents.validator import Validator
from tiles.core import Action, FLOOR, new_game
from tiles.orchestration import TurnPipeline
from tiles.sim.match import MatchConfig, MatchRunner

REQUIRED_RECORD_KEYS = {
    "step",
    "round",
    "player_index",
    "player_name",
    "tactician",
    "action",
    "state_before",
    "state_after",
    "explanation",
    "report",
    "profiles",
    "validation",
    "timing",
}


def test_full_local_match_produces_contract_shaped_records():
    config = MatchConfig(
        players=[
            {"name": "Greta", "tactician": "greedy", "config": {}},
            {"name": "Randy", "tactician": "random", "config": {"seed": 1}},
        ],
        profiler=None,
        explainer="template",
        seed=11,
    )
    events = []
    runner = MatchRunner(
        config, on_event=events.append, keep_records=True
    )
    result = runner.run()

    assert result.steps > 10
    assert len(result.scores) == 2
    assert result.winner in (0, 1)
    assert result.winner_name in ("Greta", "Randy")

    for record in result.records:
        assert set(record) >= REQUIRED_RECORD_KEYS
        assert record["validation"]["ok"] is True
        assert record["validation"]["attempts"] == 1
        assert record["timing"]["total_ms"] >= record["timing"]["decide_ms"]
        assert record["explanation"]["text"]
        assert record["state_before"]["players"][0]["name"] == "Greta"

    event_types = {e["type"] for e in events}
    assert {"status", "state", "move", "round", "game_over"} <= event_types
    game_over = [e for e in events if e["type"] == "game_over"][0]
    assert game_over["scores"] == result.scores
    assert game_over["bonuses"] is not None


def test_match_persists_to_ledger(tmp_path):
    from tiles.ledger import Ledger

    ledger = Ledger(tmp_path / "match.db")
    config = MatchConfig(
        players=[
            {"name": "A", "tactician": "greedy"},
            {"name": "B", "tactician": "random", "config": {"seed": 2}},
        ],
        profiler=None,
        explainer=None,
        seed=5,
    )
    result = MatchRunner(config, ledger=ledger).run()
    session = ledger.get_session(result.session_id)
    assert session["status"] == "completed"
    history = ledger.get_history(result.session_id)
    assert len(history) == result.steps
    export = ledger.export(result.session_id)
    assert export["session"]["result"]["winner"] == result.winner
    ledger.close()


class IllegalFirstTactician(Tactician):
    """Proposes an obviously illegal action once, then behaves."""

    name = "rigged"

    def __init__(self) -> None:
        self.calls = 0
        self._greedy = GreedyTactician()

    def decide(self, ctx: DecisionContext) -> Decision:
        self.calls += 1
        if self.calls == 1:
            # Factory 0 can never contain a color it doesn't hold AND
            # dest row 0 may be blocked; use a guaranteed-illegal source.
            return Decision(action=Action(8, 0, FLOOR))
        return self._greedy.decide(ctx)


def test_reject_edge_recovers_from_illegal_proposal():
    state = new_game(2, seed=9)
    # A 2-player game has 5 factories, so factory index 8 is illegal.
    rigged = IllegalFirstTactician()
    pipeline = TurnPipeline(
        validator=Validator(),
        tacticians={0: rigged, 1: GreedyTactician()},
        profiler=None,
        explainer=None,
    )
    record, move, _ = pipeline.run_turn(state, 1)
    assert rigged.calls == 2
    assert record["validation"]["ok"] is True
    assert record["validation"]["attempts"] == 2
    assert move.tiles_taken > 0


class AlwaysIllegalTactician(Tactician):
    name = "broken"

    def decide(self, ctx: DecisionContext) -> Decision:
        return Decision(action=Action(8, 0, FLOOR))


def test_fallback_after_repeated_illegal_proposals():
    state = new_game(2, seed=9)
    pipeline = TurnPipeline(
        validator=Validator(),
        tacticians={0: AlwaysIllegalTactician(), 1: GreedyTactician()},
        profiler=None,
        explainer=None,
    )
    record, move, _ = pipeline.run_turn(state, 1)
    assert record["validation"]["ok"] is True
    assert record["validation"]["attempts"] == 3  # 2 rejects + fallback
    assert move.tiles_taken > 0
