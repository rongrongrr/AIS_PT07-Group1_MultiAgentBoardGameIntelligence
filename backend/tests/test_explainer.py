"""Explainer tests: template rationales and LLM fallback behavior."""

from tiles.agents.base import DecisionContext
from tiles.agents.explainer import make_explainer
from tiles.agents.explainer.llm import LLMExplainer
from tiles.agents.tacticians.greedy import GreedyTactician
from tiles.core import Action, FLOOR, legal_actions, new_game


def make_ctx(seed: int = 3):
    state = new_game(2, seed=seed, player_names=["Athena", "Bob"])
    legal = legal_actions(state)
    return state, DecisionContext(state=state, player_index=0, legal=legal)


def test_template_explainer_mentions_the_move():
    state, ctx = make_ctx()
    decision = GreedyTactician().decide(ctx)
    explanation = make_explainer("template").explain(ctx, decision)
    assert explanation.text
    described = decision.action.describe()
    # The rationale names the move it explains.
    assert described in explanation.text
    assert "Athena" in explanation.text
    assert isinstance(explanation.concepts, list)
    assert "components" in explanation.evidence


def test_forced_concept_when_single_legal_action():
    state, ctx = make_ctx()
    only = ctx.legal[0]
    forced_ctx = DecisionContext(state=state, player_index=0, legal=[only])
    decision = GreedyTactician().decide(forced_ctx)
    # Force the chosen action to be the single legal one.
    decision.action = only
    explanation = make_explainer("template").explain(forced_ctx, decision)
    assert "FORCED" in explanation.concepts
    assert "only legal move" in explanation.text


def test_floor_sacrifice_concept():
    state, ctx = make_ctx()
    floor_action = next(a for a in ctx.legal if a.dest_row == FLOOR)
    decision = GreedyTactician().decide(ctx)
    decision.action = floor_action
    explanation = make_explainer("template").explain(ctx, decision)
    assert "FLOOR_SACRIFICE" in explanation.concepts


def test_explainer_handles_missing_report():
    from tiles.agents.base import Decision

    state, ctx = make_ctx()
    decision = Decision(action=ctx.legal[0], report=None)
    explanation = make_explainer("template").explain(ctx, decision)
    assert ctx.legal[0].describe() in explanation.text


def test_llm_explainer_falls_back_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    state, ctx = make_ctx()
    decision = GreedyTactician().decide(ctx)
    template_text = make_explainer("template").explain(ctx, decision).text
    llm_text = LLMExplainer().explain(ctx, decision).text
    assert llm_text == template_text
