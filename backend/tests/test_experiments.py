"""Experiments module tests: registry, every kind, stop, and the router."""

import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tiles.experiments import (
    ExperimentManager,
    get_spec,
    list_specs,
    validate_params,
)
from tiles.ledger import Ledger
from tiles.server.routers.experiments import router as experiments_router
from tiles.server.state import AppState
from tiles.sim.match import MatchConfig, MatchRunner

ALL_KINDS = {
    "profiler_ablation",
    "tournament",
    "prediction_accuracy",
    "archetype_discovery",
    "search_budget_sweep",
    "rule_extraction",
    "latency_profile",
    "xai_coverage",
    "heuristic_comparison",
    "player_count_scaling",
    "opponent_styles",
}

TINY_PARAMS = {
    "profiler_ablation": {"games": 1, "simulations": 10, "tracker": "null"},
    "tournament": {"entrants": "random,greedy", "games_per_pair": 1},
    "prediction_accuracy": {"games": 2},
    "archetype_discovery": {"games_per_preset": 1, "k": 2},
    "search_budget_sweep": {"budgets": "10,20", "games_per_budget": 1},
    "rule_extraction": {},
    "latency_profile": {},
    "xai_coverage": {},
    "heuristic_comparison": {"variants": "baseline,floor_averse", "games_per_variant": 2},
    "player_count_scaling": {"games_per_setting": 2, "player_counts": "2,3"},
    "opponent_styles": {"styles": "noisy", "games_per_cell": 2, "simulations": 10, "prediction_games": 1},
}

RESULT_KEYS = {"summary", "metrics", "tables", "series", "raw"}
RUN_KEYS = {
    "id", "kind", "title", "params", "status", "created_at", "completed_at",
    "progress", "error", "result",
}


@pytest.fixture()
def ledger(tmp_path):
    store = Ledger(tmp_path / "exp.db")
    yield store
    store.close()


def seed_ledger(ledger: Ledger) -> None:
    """One tiny recorded match so ledger-reading experiments have data."""
    config = MatchConfig(
        players=[
            {"name": "A", "tactician": "greedy", "config": {}},
            {"name": "B", "tactician": "random", "config": {"seed": 1}},
        ],
        profiler="basic",
        explainer="template",
        seed=3,
    )
    MatchRunner(config, ledger=ledger).run()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_lists_all_kinds_with_schemas():
    specs = {s.name: s for s in list_specs()}
    assert set(specs) == ALL_KINDS
    for spec in specs.values():
        d = spec.to_dict()
        assert d["title"] and d["description"] and d["report_section"]
        for p in d["params"]:
            assert p["type"] in ("int", "float", "str", "bool")
            assert set(p) >= {"name", "type", "default", "min", "max", "description"}
        # defaults must validate
        assert validate_params(spec.name, {}) == {
            **spec.defaults(),
            **validate_params(spec.name, spec.defaults()),
        }


def test_validate_params_defaults_coercion_and_errors():
    params = validate_params("profiler_ablation", {"games": "3"})
    assert params["games"] == 3 and isinstance(params["games"], int)
    assert params["simulations"] == get_spec("profiler_ablation").defaults()["simulations"]

    with pytest.raises(ValueError):
        validate_params("nope", {})
    with pytest.raises(ValueError):
        validate_params("profiler_ablation", {"games": 0})
    with pytest.raises(ValueError):
        validate_params("profiler_ablation", {"games": "many"})
    with pytest.raises(ValueError):
        validate_params("profiler_ablation", {"bogus": 1})
    with pytest.raises(ValueError):
        validate_params("profiler_ablation", {"tracker": "paper"})
    with pytest.raises(ValueError):
        validate_params("tournament", {"entrants": "greedy,unicorn"})
    with pytest.raises(ValueError):
        validate_params("search_budget_sweep", {"budgets": "ten"})


# ---------------------------------------------------------------------------
# Every kind runs end to end with the uniform result shape
# ---------------------------------------------------------------------------


def assert_result_shape(run: dict) -> None:
    assert RUN_KEYS <= set(run)
    assert run["status"] == "completed", run.get("error")
    result = run["result"]
    assert set(result) >= RESULT_KEYS
    assert isinstance(result["summary"], str) and result["summary"]
    assert all(isinstance(v, (int, float)) for v in result["metrics"].values())
    for tbl in result["tables"]:
        assert set(tbl) == {"title", "columns", "rows"}
        for row in tbl["rows"]:
            assert len(row) == len(tbl["columns"])
    for series in result["series"]:
        assert series["kind"] in ("bar", "line", "matrix")
        assert {"title", "labels", "data"} <= set(series)
        for item in series["data"]:
            assert len(item["values"]) == len(series["labels"])
        if series["kind"] == "matrix":
            assert len(series["row_labels"]) == len(series["data"])
    assert run["progress"]["done"] == run["progress"]["total"]


@pytest.mark.parametrize("kind", sorted(ALL_KINDS))
def test_each_kind_runs(kind, ledger):
    if kind in ("latency_profile", "xai_coverage"):
        seed_ledger(ledger)
    manager = ExperimentManager(ledger)
    run = manager.run_sync(kind, TINY_PARAMS[kind])
    assert_result_shape(run)
    assert run["kind"] == kind
    # Persisted and listable.
    stored = ledger.get_experiment(run["id"])
    assert stored["status"] == "completed"
    assert stored["result"]["summary"] == run["result"]["summary"]
    listed = manager.list()
    assert listed[0]["id"] == run["id"] and listed[0]["result"] is None


def test_ledger_experiments_report_empty_ledger(ledger):
    manager = ExperimentManager(ledger)
    for kind in ("latency_profile", "xai_coverage"):
        run = manager.run_sync(kind, {})
        assert run["status"] == "completed"
        assert "no recorded moves" in run["result"]["summary"]


def test_ablation_metrics_and_series(ledger):
    run = ExperimentManager(ledger).run_sync(
        "profiler_ablation", TINY_PARAMS["profiler_ablation"]
    )
    metrics = run["result"]["metrics"]
    assert {"win_rate_greedy", "win_rate_mcts", "win_rate_mcts_profiled",
            "profiler_uplift"} <= set(metrics)
    kinds = [s["kind"] for s in run["result"]["series"]]
    assert kinds.count("bar") == 3


def test_prediction_accuracy_has_phases(ledger):
    run = ExperimentManager(ledger).run_sync(
        "prediction_accuracy", TINY_PARAMS["prediction_accuracy"]
    )
    raw = run["result"]["raw"]
    assert set(raw["by_phase"]) == {"early", "mid", "late"}
    assert sum(b["n"] for b in raw["by_phase"].values()) == raw["n_predictions"]


def test_archetype_discovery_matrices(ledger):
    run = ExperimentManager(ledger).run_sync(
        "archetype_discovery", TINY_PARAMS["archetype_discovery"]
    )
    result = run["result"]
    assert result["metrics"]["n_games"] == 5
    assert 0.0 <= result["metrics"]["purity"] <= 1.0
    matrices = [s for s in result["series"] if s["kind"] == "matrix"]
    assert len(matrices) == 2
    assert matrices[0]["row_labels"] == ["blocker", "collector", "risk_taker", "cautious", "vanilla"]


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------


def test_stop_aborts_running_experiment(ledger):
    manager = ExperimentManager(ledger)
    run = manager.start(
        "tournament", {"entrants": "greedy,random", "games_per_pair": 100}
    )
    assert run["status"] in ("created", "running")
    time.sleep(0.3)
    manager.stop(run["id"])
    deadline = time.time() + 20
    status = None
    while time.time() < deadline:
        status = manager.get(run["id"])["status"]
        if status in ("aborted", "completed", "failed"):
            break
        time.sleep(0.1)
    assert status == "aborted"
    final = manager.get(run["id"])
    assert final["result"]["summary"].startswith("Stopped early")
    assert 0 < final["result"]["metrics"]["games_played"] < 100
    with pytest.raises(KeyError):
        manager.stop("exp_missing")
    assert manager.delete(run["id"]) is True
    assert manager.get(run["id"]) is None


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(ledger):
    manager = ExperimentManager(ledger)
    app = FastAPI()
    app.state.tiles = AppState(
        ledger=ledger, sessions=None, experiments=manager, loop=None
    )
    app.include_router(experiments_router)

    @app.on_event("startup")
    async def _capture_loop() -> None:
        manager.loop = asyncio.get_running_loop()
        app.state.tiles.loop = manager.loop

    with TestClient(app) as test_client:
        yield test_client
    manager.shutdown()


def test_router_lifecycle(client):
    types = client.get("/api/experiments/types").json()
    assert {t["name"] for t in types} == ALL_KINDS

    assert client.post("/api/experiments", json={"kind": "nope"}).status_code == 422
    assert client.post(
        "/api/experiments", json={"kind": "rule_extraction", "params": {"extractor": "x"}}
    ).status_code == 422
    assert client.get("/api/experiments/exp_missing").status_code == 404
    assert client.post("/api/experiments/exp_missing/stop").status_code == 404
    assert client.delete("/api/experiments/exp_missing").status_code == 404

    created = client.post("/api/experiments", json={"kind": "rule_extraction"})
    assert created.status_code == 201
    run_id = created.json()["id"]
    assert created.json()["kind"] == "rule_extraction"

    deadline = time.time() + 30
    status = None
    while time.time() < deadline:
        status = client.get(f"/api/experiments/{run_id}").json()["status"]
        if status in ("completed", "failed", "aborted"):
            break
        time.sleep(0.1)
    assert status == "completed"
    detail = client.get(f"/api/experiments/{run_id}").json()
    assert detail["result"]["metrics"]["accuracy"] == 1.0

    listed = client.get("/api/experiments").json()
    assert listed[0]["id"] == run_id and listed[0]["result"] is None

    assert client.post(f"/api/experiments/{run_id}/stop").json() == {"status": "aborting"}
    assert client.delete(f"/api/experiments/{run_id}").json() == {"deleted": run_id}
    assert client.get(f"/api/experiments/{run_id}").status_code == 404


def test_router_websocket_stream(client):
    run_id = client.post(
        "/api/experiments",
        json={"kind": "prediction_accuracy", "params": {"games": 1}},
    ).json()["id"]
    types = set()
    result = None
    with client.websocket_connect(f"/api/experiments/{run_id}/ws") as ws:
        deadline = time.time() + 30
        while time.time() < deadline:
            event = ws.receive_json()
            types.add(event["type"])
            if event["type"] == "result":
                result = event["result"]
            if event["type"] == "status" and event["status"] in (
                "completed", "failed", "aborted"
            ):
                break
    assert {"status", "progress", "result"} <= types
    assert result is not None and result["metrics"]["games"] == 1

    # Late subscriber on a finished run still gets history.
    with client.websocket_connect(f"/api/experiments/{run_id}/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "status"

    # Delete while running -> 409.
    busy = client.post(
        "/api/experiments",
        json={"kind": "tournament", "params": {"entrants": "greedy,random", "games_per_pair": 50}},
    ).json()["id"]
    time.sleep(0.2)
    assert client.delete(f"/api/experiments/{busy}").status_code == 409
    client.post(f"/api/experiments/{busy}/stop")
