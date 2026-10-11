"""Heuristic and player-count studies: per-game statistics and drivers."""

import pytest

from tiles.experiments import validate_params
from tiles.sim.study import (
    HEURISTICS,
    heuristic_study,
    heuristic_weights,
    mean_ci,
    play_game,
    scaling_study,
    summarise,
    wilson,
)


def seats(n, tactician="greedy"):
    return [{"label": f"L{i}", "tactician": tactician, "config": {}} for i in range(n)]


@pytest.mark.parametrize("n", [2, 3, 4])
def test_play_game_records_consistent_per_player_stats(n):
    game = play_game(seats(n), seed=3, game_id=7, setting="t")
    assert game["game"] == 7 and game["num_players"] == n and len(game["players"]) == n
    assert sorted(game["finish_order"]) == list(range(1, n + 1))
    for p in game["players"]:
        # The score decomposes exactly into tiling points, floor penalties and bonuses
        # (a score is never negative in Azul, so it is clamped at 0).
        assert p["score"] == max(0, p["tiling_points"] + p["floor_penalty"] + p["bonus_points"])
        assert p["moves"] > 0
        assert 0 <= p["floor_move_share"] <= 1 and 0 <= p["center_move_share"] <= 1
        assert p["rank"] >= 1
    assert sum(p["won"] + p["shared"] for p in game["players"]) >= 1


def test_play_game_is_deterministic_for_a_seed():
    a = play_game(seats(2), seed=5)
    b = play_game(seats(2), seed=5)
    assert a["scores"] == b["scores"] and a["steps"] == b["steps"]


def test_heuristic_weights_and_unknown_names():
    base = heuristic_weights("baseline")
    assert heuristic_weights("floor_averse")["floor_penalty"] > base["floor_penalty"]
    assert set(heuristic_weights("myopic")) == set(base)
    with pytest.raises(ValueError):
        heuristic_weights("nope")


def test_heuristic_study_rotates_focal_seat_and_reports_progress():
    progress = []
    games = heuristic_study(["baseline", "denial_heavy"], 3, 6, seed=1,
                            on_progress=lambda d, t, m: progress.append((d, t)))
    assert len(games) == 12
    assert {g["focal_seat"] for g in games} == {1, 2, 3}
    assert progress[-1] == (12, 12)
    focal = summarise([g for g in games if g["setting"] == "baseline"], label="focal")
    assert focal["player_games"] == 6 and 0 <= focal["win_rate"] <= 1


def test_studies_honour_stop_check():
    assert heuristic_study(["baseline"], 2, 5, 0, stop_check=lambda: True) == []
    assert scaling_study("greedy", {}, [2], 5, 0, stop_check=lambda: True) == []


def test_scaling_study_has_self_and_field_tables():
    games = scaling_study("greedy", {}, [2, 3], 2, seed=0, opponent="random")
    assert {g["setting"] for g in games} == {"self-2p", "field-2p", "self-3p", "field-3p"}
    field = [g for g in games if g["setting"] == "field-3p"]
    assert {p["label"] for g in field for p in g["players"]} == {"focal", "filler"}
    assert summarise(field, label="focal")["win_rate"] >= 0.0
    assert summarise(games, tactician="greedy")["player_games"] > 0


def test_statistics_helpers():
    assert mean_ci([]) == (0.0, 0.0)
    assert mean_ci([4.0]) == (4.0, 0.0)
    m, hw = mean_ci([1, 2, 3, 4])
    assert m == 2.5 and hw > 0
    assert wilson(0, 0) == (0.0, 0.0)
    lo, hi = wilson(50, 100)
    assert lo < 0.5 < hi
    assert summarise([])["win_rate"] == 0.0


def test_experiment_param_validation():
    with pytest.raises(ValueError):
        validate_params("heuristic_comparison", {"variants": "nope"})
    with pytest.raises(ValueError):
        validate_params("heuristic_comparison", {"variants": " , "})
    with pytest.raises(ValueError):
        validate_params("player_count_scaling", {"tactician": "unicorn"})
    with pytest.raises(ValueError):
        validate_params("player_count_scaling", {"opponent": "unicorn"})
    with pytest.raises(ValueError):
        validate_params("player_count_scaling", {"player_counts": "2,9"})
    with pytest.raises(ValueError):
        validate_params("player_count_scaling", {"player_counts": "a,b"})
    assert set(HEURISTICS) >= {"baseline", "myopic"}


def test_scaling_study_can_run_one_table_type_and_validates_modes():
    games = scaling_study("greedy", {}, [2], 2, seed=0, modes=("field",))
    assert {g["setting"] for g in games} == {"field-2p"}
    with pytest.raises(ValueError):
        validate_params("player_count_scaling", {"modes": "other"})


def test_heuristic_study_with_a_different_opponent():
    games = heuristic_study(["baseline"], 2, 2, seed=0, opponent="minimax")
    assert {p["tactician"] for g in games for p in g["players"]} == {"greedy", "minimax"}
    with pytest.raises(ValueError):
        validate_params("heuristic_comparison", {"opponent": "unicorn"})


def test_session_accepts_boolean_tactician_settings(tmp_path):
    from fastapi.testclient import TestClient

    from tiles.server.app import create_app

    client = TestClient(create_app(db_path=str(tmp_path / "tiles.db")))
    players = [
        {"name": "A", "tactician": "greedy", "config": {"table_aware": True, "endgame_aware": False}},
        {"name": "B", "tactician": "greedy", "config": {}},
    ]
    assert client.post("/api/sessions", json={"players": players}).status_code == 201
    players[0]["config"]["table_aware"] = "yes"
    bad = client.post("/api/sessions", json={"players": players})
    assert bad.status_code == 422 and "must be of type bool" in bad.text


class _Ctx:
    def progress(self, done, total, message=""):
        pass

    def stopped(self):
        return False


def _assert_stats(rows, players_per_game):
    assert rows
    for g in rows:
        assert len(g["players"]) == players_per_game
        for p in g["players"]:
            # Scores are floored at zero after every round, so the final score can be
            # higher than the plain sum when a player is thrown back to zero mid-game.
            assert p["score"] >= max(0, p["tiling_points"] + p["floor_penalty"] + p["bonus_points"])


def test_tournament_saves_per_game_statistics_without_changing_results():
    from tiles.sim.tournament import run_tournament

    entrants = [{"name": "greedy", "tactician": "greedy", "config": {}},
                {"name": "random", "tactician": "random", "config": {}}]
    out = run_tournament(entrants, games_per_pair=2, seed=3)
    assert len(out.game_stats) == len(out.games) == 2
    _assert_stats(out.game_stats, 2)
    assert [g["scores"] for g in out.games] == [g["scores"] for g in out.game_stats]
    assert {p["label"] for g in out.game_stats for p in g["players"]} == {"greedy", "random"}


def test_ablation_and_sweep_save_per_game_statistics():
    from tiles.experiments.kinds import search_budget_sweep
    from tiles.sim.ablation import run_ablation

    conditions = run_ablation(games=1, simulations=10, seed=1, tracker_backend="null", verbose=False)
    stats = [g for c in conditions for g in c.game_stats]
    assert len(stats) == 3
    _assert_stats(stats, 2)
    assert {p["label"] for g in stats for p in g["players"]} == {"subject", "blocker"}

    result = search_budget_sweep.run({"budgets": "5", "games_per_budget": 2, "seed": 1}, _Ctx())
    assert len(result["raw"]["game_stats"]) == 2
    _assert_stats(result["raw"]["game_stats"], 2)


def test_style_opponents_play_legal_distinct_games():
    from tiles.agents.base import DecisionContext
    from tiles.agents.tacticians import make_tactician
    from tiles.agents.tacticians.styles import HABITS, style_names
    from tiles.core import legal_actions, new_game

    state = new_game(2, seed=3)
    legal = legal_actions(state)
    ctx = DecisionContext(state, 0, legal)
    for name in style_names():
        decision = make_tactician(f"style_{name}", seed=1).decide(ctx)
        assert decision.action in legal and decision.report.candidates
    assert set(HABITS) == {"colour_loyal", "centre_averse", "low_rows"}
    with pytest.raises(ValueError):
        make_tactician("style_nope")
    # The habits really change what is played.
    differs = 0
    for seed in range(1, 11):
        st = new_game(2, seed=seed)
        c = DecisionContext(st, 0, legal_actions(st))
        plain = make_tactician("greedy").decide(c).action
        differs += sum(make_tactician(f"style_{name}").decide(c).action != plain for name in HABITS)
    assert differs > 0


def test_opponent_styles_experiment_runs_and_validates():
    from tiles.experiments.kinds import opponent_styles

    result = opponent_styles.run(
        {"styles": "centre_averse,noisy", "games_per_cell": 2, "simulations": 5, "prediction_games": 1, "seed": 2,
         "profiler": "extended", "habit_rate": 0.25}, _Ctx()
    )
    assert len(result["raw"]["game_stats"]) == 8
    assert [t["title"][:8] for t in result["tables"]] == ["Win rate", "Opponent", "Next-mov"]
    with pytest.raises(ValueError):
        validate_params("opponent_styles", {"styles": "unknown"})
    with pytest.raises(ValueError):
        validate_params("opponent_styles", {"styles": " , "})


def test_extended_profiler_learns_a_colour_habit_and_stays_valid():
    from tiles.agents.profiler import make_profiler
    from tiles.agents.profiler.habits import HABIT_KEYS, ExtendedProfiler, habit_features
    from tiles.core import legal_actions, new_game, step

    for a in legal_actions(new_game(2, seed=1))[:5]:
        f = habit_features(a)
        assert set(f) == set(HABIT_KEYS) and sum(f[k] for k in HABIT_KEYS if k.startswith("habit_colour")) == 1.0
    assert "extended" not in __import__("tiles.agents.profiler", fromlist=["PROFILERS"]).PROFILERS  # not offered in the app
    with pytest.raises(ValueError):
        make_profiler("extended")

    import random

    from tiles.agents.base import DecisionContext
    from tiles.agents.tacticians import make_tactician
    from tiles.core import deal_round

    profiler = ExtendedProfiler(habit_rate=0.5)
    for game in range(3):
        state = new_game(2, seed=40 + game)
        rng = random.Random(game)
        players = [make_tactician("style_colour_loyal"), make_tactician("greedy")]
        while not state.is_game_over:
            legal = legal_actions(state)
            mover = state.current_player
            action = players[mover].decide(DecisionContext(state, mover, legal)).action
            before = state.clone()
            move, round_result = step(state, action)
            profiler.observe(before, action, move)
            if round_result is not None and not round_result.game_over:
                deal_round(state, rng)
    weights = profiler.predictor.weights_for(0)
    assert weights["habit_colour_0"] > 0  # blue is the favourite colour
    dist = profiler.predict(new_game(2, seed=9), 0, legal_actions(new_game(2, seed=9)))
    assert abs(sum(dist.values()) - 1.0) < 1e-6
