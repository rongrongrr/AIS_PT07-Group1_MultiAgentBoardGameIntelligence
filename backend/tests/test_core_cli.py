"""Smoke tests for the ``tiles`` command-line interface and the sim/telemetry modules behind it."""

import json

from tiles import cli
from tiles.telemetry.tracker import JsonlTracker, NullTracker, get_tracker


def test_verify_rules(capsys):
    assert cli.main(["verify-rules"]) == 0
    assert "verified" in capsys.readouterr().out


def test_play_records_ledger(tmp_path, capsys):
    db = tmp_path / "ledger.db"
    rc = cli.main(["play", "--player", "a=greedy", "--player", "b=random", "--seed", "2",
                   "--no-explain", "--db", str(db)])
    assert rc == 0 and db.exists()
    assert "game over" in capsys.readouterr().out


def test_tournament_writes_output(tmp_path):
    out = tmp_path / "t.json"
    rc = cli.main(["tournament", "--player", "g=greedy", "--player", "r=random",
                   "--games-per-pair", "2", "--simulations", "10", "--seed", "1", "--output", str(out)])
    assert rc == 0
    assert json.loads(out.read_text())


def test_ablate_and_predict_eval(capsys):
    assert cli.main(["ablate", "--games", "1", "--simulations", "10", "--tracker", "null"]) == 0
    assert cli.main(["predict-eval", "--games", "1"]) == 0


def test_trackers(tmp_path):
    assert type(get_tracker("null")) is NullTracker
    path = tmp_path / "x.jsonl"
    t = get_tracker("jsonl", path=str(path))
    assert isinstance(t, JsonlTracker)
    with t.run("r1", {"a": 1}):
        t.log_params({"b": 2})
        t.log_metrics({"m": 1.0}, step=3)
    events = [json.loads(line)["event"] for line in path.read_text().splitlines()]
    assert events == ["run_start", "params", "metrics", "run_end"]
    with NullTracker().run("n"):
        pass
