"""MLflow tracking: runs are recorded with the right content, and failures never propagate."""

import asyncio
import json

import pytest

from app import tracking
from app.models.db import Move, Session
from tests.test_orchestration import make_session, run_game, setup

mlflow = pytest.importorskip("mlflow")


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.delenv("TILES_MLFLOW_DISABLED", raising=False)
    uri = "sqlite:///" + (tmp_path / "mlflow.db").as_posix()
    monkeypatch.setenv("TILES_MLFLOW_URI", uri)
    return uri


def runs(uri, experiment):
    mlflow.set_tracking_uri(uri)
    exp = mlflow.get_experiment_by_name(experiment)
    return mlflow.search_runs([exp.experiment_id], output_format="list") if exp else []


def test_log_run_records_params_metrics_tags_series_and_artifacts(store):
    rid = tracking.log_run("unit", "run-1", params={"a": 1}, metrics={"m": 2.5, "skip": None},
                           tags={"kind": "x"}, artifacts={"blob": {"k": [1, 2]}}, series={"s": [1, 2, 3]})
    assert rid
    (run,) = runs(store, "unit")
    assert run.data.params == {"a": "1"} and run.data.metrics["m"] == 2.5 and "skip" not in run.data.metrics
    assert run.data.tags["kind"] == "x" and run.data.metrics["s"] == 3.0       # last step of the series
    client = mlflow.tracking.MlflowClient(store)
    assert any(a.path == "blob.json" for a in client.list_artifacts(rid))
    assert tracking._artifact_root("http://server:5000", "e") is None


def test_disabled_and_failures_are_silent(monkeypatch, tmp_path):
    monkeypatch.setenv("TILES_MLFLOW_DISABLED", "1")
    assert tracking.log_run("x", "y") is None and not tracking.enabled()
    monkeypatch.delenv("TILES_MLFLOW_DISABLED")
    monkeypatch.setenv("TILES_MLFLOW_URI", "http://127.0.0.1:1/nothing-listens-here")
    assert tracking.log_run("x", "y", metrics={"a": 1}) is None               # unreachable server: ignored
    assert tracking.log_session_run("no-such-session") is None
    monkeypatch.setattr(tracking, "_mlflow", lambda: None)
    assert tracking.log_run("x", "y") is None


def test_default_store_is_a_sqlite_file_in_mlruns(monkeypatch):
    monkeypatch.delenv("TILES_MLFLOW_URI", raising=False)
    assert tracking.tracking_uri().startswith("sqlite:///") and tracking.tracking_uri().endswith("mlruns/mlflow.db")


def test_summarize_game_computes_telemetry():
    moves = [
        {"system_tag": "A", "decision_time_ms": 10, "click_ms": 100, "total_ms": 300, "legal_actions": 40,
         "action": {"destination": "pattern_line"}},
        {"system_tag": "B", "decision_time_ms": 30, "click_ms": 200, "total_ms": 500, "legal_actions": 20,
         "action": {"destination": "floor"}, "fell_back_to_floor": True},
    ]
    s = tracking.summarize_game({"final_scores": {"X": 50, "Y": 30}}, moves)
    m = s["metrics"]
    assert m["total_moves"] == 2 and m["winning_margin"] == 20 and m["final_score.X"] == 50
    assert m["avg_decision_time_ms"] == 20 and m["max_total_ms"] == 500
    assert m["avg_decision_ms.B"] == 30 and m["floor_move_share"] == 0.5 and m["floor_fallbacks"] == 1
    assert s["series"]["decision_time_ms"] == [10, 30]
    assert tracking.summarize_game({}, [])["metrics"]["floor_move_share"] == 0.0


def test_finished_game_is_logged_with_its_telemetry(store, db):
    platform, mp, models = setup(db)
    row = run_game(db, mp, models)
    assert row.status == "completed"
    automatic = len(runs(store, tracking.GAMES_EXPERIMENT))      # the game loop logs by itself on completion
    rid = tracking.log_session_run("sess_test")                  # and it can be re-logged explicitly
    assert rid
    all_runs = runs(store, tracking.GAMES_EXPERIMENT)
    assert automatic >= 1 and len(all_runs) == automatic + 1
    run = next(r for r in all_runs if r.info.run_id == rid)
    assert run.data.tags["status"] == "completed" and run.data.tags["winner"] == row.winner
    assert run.data.metrics["total_moves"] == platform.moves_applied
    assert "final_score.Alice" in run.data.metrics and run.data.metrics["avg_decision_time_ms"] >= 0
    assert "GreedyPlayer" in run.data.params["players"]
    client = mlflow.tracking.MlflowClient(store)
    art = client.download_artifacts(rid, "moves.json")
    assert len(json.load(open(art))) == platform.moves_applied
