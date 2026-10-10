"""OpponentModel: style inference and next-move prediction."""

import asyncio


from tiles.azul.game import new_game, play_game
from tiles.azul.rules import get_legal_actions
from tiles.ml.greedy_player import ARCHETYPES, BlockerPlayer, GreedyPlayer, RecklessPlayer
from tiles.ml.opponent_model import STYLE_LIBRARY, OpponentModel, move_distribution


def run(c):
    return asyncio.run(c)


def observe_game(player, partner, seed, model, name="OPP"):
    log = []

    def hook(sim, idx, action):
        if sim.state.players[idx].name == name:
            log.append((sim.state.model_copy(deep=True), idx, action))

    run(play_game([player.decide, partner.decide], [name, "PARTNER"], seed=seed, on_move=hook))
    for state, idx, action in log:
        model.observe(state, idx, action)
    return log


def test_move_distribution_is_a_probability_distribution():
    sim = new_game(["A", "B"], seed=1)
    acts, probs = move_distribution(sim.state, 0, ARCHETYPES["GreedyPlayer"], 1.0)
    assert len(acts) == len(probs) > 0 and abs(sum(probs) - 1) < 1e-9
    sim.state.factories = [[] for _ in sim.state.factories]
    sim.state.center_pool = []
    assert move_distribution(sim.state, 0, ARCHETYPES["GreedyPlayer"], 1.0) == ([], [])


def test_posterior_concentrates_on_the_true_style():
    m = OpponentModel()
    assert abs(sum(m.posterior().values()) - 1) < 1e-9          # uniform before evidence
    observe_game(RecklessPlayer(), GreedyPlayer(), 3, m)
    style, p = m.likely_style()
    assert style == "RecklessPlayer" and p > 0.5 and m.observed > 10


def test_blocker_is_identified_and_reset_clears_evidence():
    m = OpponentModel()
    observe_game(BlockerPlayer(), GreedyPlayer(), 4, m)
    assert m.likely_style()[0] == "BlockerPlayer"
    m.reset()
    assert m.observed == 0 and len({round(v, 6) for v in m.posterior().values()}) == 1


def test_predicts_next_move_better_than_chance():
    m = OpponentModel()
    log = observe_game(GreedyPlayer(), GreedyPlayer(), 5, OpponentModel(), name="OPP")
    hits = n = 0
    for t, (state, idx, action) in enumerate(log):
        if t >= 6:
            top = m.predict(state, idx, k=3)
            assert 1 <= len(top) <= 3 and top[0][1] >= top[-1][1]
            hits += any(a == action for a, _ in top)
            n += 1
        m.observe(state, idx, action)
    assert hits / n > 0.7                                        # chance is ~0.2


def test_unobserved_action_does_not_zero_a_style():
    m = OpponentModel()
    sim = new_game(["A", "B"], seed=2)
    other = list(get_legal_actions(sim.state, 0))[-1]
    m.observe(sim.state, 0, other)
    assert all(v > -50 for v in m.log_lik.values())
    assert set(m.styles) == set(STYLE_LIBRARY)
