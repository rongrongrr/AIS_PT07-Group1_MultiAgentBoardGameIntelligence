"""Explainer: rationale content, and faithfulness of every claim checked by simulating the move."""

import asyncio
import random

import pytest

from app.azul.game import apply_action, floor_size, new_game, play_game, score_round
from app.azul.rules import calculate_floor_penalty, get_legal_actions
from app.explain.explainer import Explainer, LLMExplainer, move_facts
from app.ml.minimax_player import MinimaxPlayer
from app.ml.random_player import RandomPlayer
from app.models.schemas import DestinationType, GameAction, SourceType, TileColor


def positions(games=4, per_state=6, seed=0):
    """(state, player_index, action) triples from simulated games, sampled over legal moves."""
    rng = random.Random(seed)
    out = []

    for g in range(games):
        players = [RandomPlayer(seed=g), RandomPlayer(seed=g + 50)]

        def hook(sim, idx, action):
            legal = get_legal_actions(sim.state, idx)
            for a in rng.sample(legal, min(per_state, len(legal))):
                out.append((sim.state.model_copy(deep=True), idx, a))

        asyncio.run(play_game([p.decide for p in players], ["A", "B"], seed=seed * 100 + g, on_move=hook))
    return out


POSITIONS = positions()


def simulate(state, idx, action):
    sim = new_game(["A", "B"], seed=0)
    sim.state = state.model_copy(deep=True)
    sim.current = idx
    sim.bag, sim.lid = [], []
    before = sim.state.players[idx].model_copy(deep=True)
    center_before = len(sim.state.center_pool)
    apply_action(sim, action)
    return sim, before, center_before


def test_there_are_enough_positions():
    assert len(POSITIONS) > 1500


def test_every_claim_matches_the_simulated_outcome():
    checked = 0
    for state, idx, action in POSITIONS:
        f = move_facts(state, idx, action)
        sim, before, center_before = simulate(state, idx, action)
        after = sim.state.players[idx]

        # tiles taken / left for others
        if action.source_type == SourceType.FACTORY:
            src = state.factories[action.source_index]
            assert f["picked"] == sum(1 for t in src if t == action.color)
            assert sim.state.factories[action.source_index] == []
            assert f["leaves_in_center"] == len(sim.state.center_pool) - center_before
        else:
            assert f["picked"] == center_before - len(sim.state.center_pool) - (1 if f["takes_token"] else 0)
            assert f["leaves_in_center"] == 0

        # first-player token
        assert f["takes_token"] == (after.has_first_player_token and not before.has_first_player_token)

        # overflow onto the floor, and its price
        floor_growth = floor_size(after) - floor_size(before)
        assert floor_growth == f["overflow"] + (1 if f["takes_token"] else 0) or floor_size(after) == 7
        if floor_size(after) < 7:
            expected_penalty = calculate_floor_penalty(floor_size(after)) - calculate_floor_penalty(floor_size(before))
            assert f["floor_penalty"] == expected_penalty

        # line completion
        if action.destination == DestinationType.PATTERN_LINE:
            row = action.destination_row
            assert f["completes_line"] == (len(after.pattern_lines[row]) == row + 1)
            assert f["line_fill"] == f"{len(after.pattern_lines[row])}/{row + 1}"
        else:
            assert not f["completes_line"] and f["line_fill"] is None
        checked += 1
    assert checked == len(POSITIONS)


def test_line_points_match_what_the_engine_awards_at_round_end():
    """Isolate the moved line, run the engine's real round scoring, compare the score delta."""
    verified = 0
    for state, idx, action in POSITIONS:
        f = move_facts(state, idx, action)
        if not f["completes_line"]:
            continue
        sim, before, _ = simulate(state, idx, action)
        p = sim.state.players[idx]
        for r in range(5):
            if r != action.destination_row:
                p.pattern_lines[r] = []
        p.floor_line, p.has_first_player_token = [], False
        p.score = 100
        score_round(sim)
        assert p.score - 100 == f["line_points"], (action, f)
        verified += 1
    assert verified > 100


def test_denial_claim_matches_opponent_lines():
    for state, idx, action in POSITIONS[:600]:
        f = move_facts(state, idx, action)
        for name in f["denies"]:
            opp = next(p for p in state.players if p.name == name)
            assert any(line and line[0] == action.color and len(line) < r + 1
                       for r, line in enumerate(opp.pattern_lines))
        for opp in state.players:
            if opp.name != state.players[idx].name and opp.name not in f["denies"]:
                assert not any(line and line[0] == action.color and len(line) < r + 1
                               for r, line in enumerate(opp.pattern_lines))


# ------------------------------------------------------------------ text

def test_rationale_mentions_the_decisive_facts():
    sim = new_game(["Alice", "Bob"], seed=2)
    sim.state.players[0].pattern_lines[1] = [TileColor.RED]
    sim.state.factories[0] = [TileColor.RED, TileColor.RED, TileColor.BLUE, TileColor.BLUE]
    sim.state.players[1].pattern_lines[2] = [TileColor.RED]
    act = GameAction(source_type=SourceType.FACTORY, source_index=0, color=TileColor.RED,
                     destination=DestinationType.PATTERN_LINE, destination_row=1)
    out = Explainer().explain(sim.state, 0, act)
    text = out["rationale"]
    assert "Alice takes 2 red from Factory 1" in text and "row 2" in text
    assert "completes the line" in text and "overflow" in text            # 2 tiles into a 2-slot line with 1 filled
    assert "denies Bob" in text and "2 tiles move to the center" in text


def test_floor_dump_and_token_wording():
    sim = new_game(["Alice", "Bob"], seed=3)
    sim.state.center_pool = ["red", "red", "firstPlayer"]
    act = GameAction(source_type=SourceType.CENTER, color=TileColor.RED, destination=DestinationType.FLOOR)
    text = Explainer().explain(sim.state, 0, act)["rationale"]
    assert "straight on the floor" in text and "first-player token" in text
    assert Explainer().commentary(sim.state, 0, act).startswith("Alice takes 2 red from the center, onto the floor")


def test_rationale_includes_search_comparison_and_opponent_read():
    sim = new_game(["Alice", "Bob"], seed=4)
    p = MinimaxPlayer(depth=2)
    a = asyncio.run(p.decide(sim.state, 0))
    exp = dict(p.last_explanation)
    exp["adaptation"] = {"opponents": {"Bob": {"style": "BlockerPlayer", "confidence": 0.8}}}
    text = Explainer().explain(sim.state, 0, a, exp)["rationale"]
    assert "MinimaxPlayer rated it" in text and "ahead of the next option" in text
    assert "Bob looks like BlockerPlayer (80% sure)" in text


def test_commentary_is_one_line():
    sim = new_game(["Alice", "Bob"], seed=5)
    a = get_legal_actions(sim.state, 0)[0]
    line = Explainer().commentary(sim.state, 0, a)
    assert line.startswith("Alice takes") and line.endswith(".") and "\n" not in line


def test_llm_explainer_rewrites_but_falls_back_on_failure():
    sim = new_game(["Alice", "Bob"], seed=6)
    a = get_legal_actions(sim.state, 0)[0]
    seen = {}

    def good(system, user):
        seen["user"] = user
        return "A friendlier version."

    out = LLMExplainer(good).explain(sim.state, 0, a)
    assert out["rationale"] == "A friendlier version." and out["rationale_template"].startswith("Alice takes")
    assert "Facts:" in seen["user"]

    def broken(system, user):
        raise RuntimeError("no network")

    assert LLMExplainer(broken).explain(sim.state, 0, a)["rationale"].startswith("Alice takes")
