"""Remaining untested paths: LLM explainer (fake client), core state
serialisation, and the LLM rule-extraction fallback."""

import json
import sys
import types

from tiles.agents.base import DecisionContext
from tiles.agents.explainer.llm import LLMExplainer
from tiles.agents.tacticians.greedy import GreedyTactician
from tiles.core import GameState, legal_actions, new_game, step


# ------------------------------------------------------------------ core state

def test_core_state_round_trips_through_json_view():
    state = new_game(3, seed=4, player_names=["A", "B", "C"])
    for _ in range(9):
        step(state, legal_actions(state)[0])
    clone = GameState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert clone.to_dict() == state.to_dict()
    assert clone.scores() == state.scores() and clone.current_player == state.current_player
    assert not clone.is_game_over and clone.winner() is None


# ------------------------------------------------------------------ LLM explainer

def _ctx():
    state = new_game(2, seed=3, player_names=["Athena", "Bob"])
    return DecisionContext(state=state, player_index=0, legal=legal_actions(state))


def _fake_anthropic(monkeypatch, replies):
    calls = []

    class Messages:
        def create(self, **kw):
            calls.append(kw)
            r = replies.pop(0)
            if isinstance(r, Exception):
                raise r
            return types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text=r)])

    mod = types.ModuleType("anthropic")
    mod.Anthropic = lambda: types.SimpleNamespace(messages=Messages())
    monkeypatch.setitem(sys.modules, "anthropic", mod)
    return calls


def test_llm_explainer_rewrites_and_keeps_template_as_evidence(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    calls = _fake_anthropic(monkeypatch, ["Athena grabs the reds. A bold start."])
    ctx = _ctx()
    out = LLMExplainer().explain(ctx, GreedyTactician().decide(ctx))
    assert out.text == "Athena grabs the reds. A bold start."
    assert out.evidence["template_text"] and "Candidates considered" in calls[0]["messages"][0]["content"]
    assert calls[0]["model"] == "claude-opus-5-5"


def test_llm_explainer_retries_once_then_falls_back(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    ctx = _ctx()
    decision = GreedyTactician().decide(ctx)
    _fake_anthropic(monkeypatch, [RuntimeError("down"), "Recovered text."])
    assert LLMExplainer().explain(ctx, decision).text == "Recovered text."
    _fake_anthropic(monkeypatch, [RuntimeError("down"), RuntimeError("down")])
    out = LLMExplainer().explain(ctx, decision)
    assert "template_text" not in out.evidence and "Athena" in out.text      # plain template rationale
    _fake_anthropic(monkeypatch, ["   ", ""])
    assert "template_text" not in LLMExplainer().explain(ctx, decision).evidence


def test_llm_explainer_without_key_or_package_uses_template(monkeypatch):
    ctx = _ctx()
    decision = GreedyTactician().decide(ctx)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert "template_text" not in LLMExplainer().explain(ctx, decision).evidence
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setitem(sys.modules, "anthropic", None)                      # import fails
    assert "template_text" not in LLMExplainer().explain(ctx, decision).evidence


# ------------------------------------------------------------------ LLM rule extraction

def test_rulebook_llm_extraction_parses_reply_and_falls_back(monkeypatch):
    from tiles.rulebook import extract as X
    from tiles.rulebook.ingest import RulebookIndex
    index = RulebookIndex.build()
    fallback = X.extract_rules_deterministic(index)
    _fake_anthropic(monkeypatch, ["not json at all"])
    assert [s.id for s in X.extract_rules_llm(index)] == [s.id for s in fallback]
    one = fallback[0].to_dict()
    _fake_anthropic(monkeypatch, ["Here you go: " + json.dumps([one])])
    got = X.extract_rules_llm(index)
    assert [s.id for s in got] == [fallback[0].id]
