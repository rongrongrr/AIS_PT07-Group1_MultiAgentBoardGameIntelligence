"""Ledger tests: immutability, round-trips, export completeness."""

import sqlite3

import pytest

from tiles.ledger import Ledger


@pytest.fixture()
def ledger(tmp_path):
    store = Ledger(tmp_path / "test.db")
    yield store
    store.close()


def sample_record(step: int) -> dict:
    return {
        "step": step,
        "round": 1,
        "player_index": step % 2,
        "player_name": f"p{step % 2}",
        "action": {"source_type": "factory", "source_index": 0, "color": "blue"},
        "state_before": {"round": 1},
        "state_after": {"round": 1},
        "timing": {"decide_ms": 1.5},
    }


def test_session_lifecycle_and_history_roundtrip(ledger):
    ledger.create_session("sess_1", mode="local", config={"seed": 7})
    ledger.set_status("sess_1", "running")

    records = [sample_record(i) for i in range(1, 4)]
    for record in records:
        ledger.record_move("sess_1", record)
    ledger.record_round("sess_1", 1, {"round": 1, "scores": [4, 2]})
    ledger.save_profiles(
        "sess_1",
        [
            {"player_index": 0, "archetype": "aggressive_blocker"},
            {"player_index": 1, "archetype": "cautious_optimizer"},
        ],
    )
    ledger.finish_session("sess_1", {"winner": 0, "scores": [40, 22]})

    history = ledger.get_history("sess_1")
    assert history == records  # exact JSON round-trip

    session = ledger.get_session("sess_1")
    assert session["status"] == "completed"
    assert session["result"] == {"winner": 0, "scores": [40, 22]}
    assert session["config"] == {"seed": 7}
    assert session["completed_at"] is not None


def test_export_contains_all_sections(ledger):
    ledger.create_session("sess_2")
    ledger.record_move("sess_2", sample_record(1))
    ledger.record_round("sess_2", 1, {"round": 1})
    ledger.save_profiles("sess_2", [{"player_index": 0, "archetype": "x"}])

    export = ledger.export("sess_2")
    assert set(export) == {"session", "rounds", "moves", "profiles"}
    assert len(export["moves"]) == 1
    assert len(export["rounds"]) == 1
    assert len(export["profiles"]) == 1

    with pytest.raises(KeyError):
        ledger.export("nope")


def test_duplicate_step_rejected(ledger):
    ledger.create_session("sess_3")
    ledger.record_move("sess_3", sample_record(1))
    with pytest.raises(sqlite3.IntegrityError):
        ledger.record_move("sess_3", sample_record(1))


def test_profile_upsert_updates_in_place(ledger):
    ledger.create_session("sess_4")
    ledger.save_profiles("sess_4", [{"player_index": 0, "archetype": "a"}])
    ledger.save_profiles("sess_4", [{"player_index": 0, "archetype": "b"}])
    profiles = ledger.get_profiles("sess_4")
    assert len(profiles) == 1
    assert profiles[0]["archetype"] == "b"


def test_list_sessions(ledger):
    ledger.create_session("sess_a")
    ledger.create_session("sess_b")
    ids = {s["id"] for s in ledger.list_sessions()}
    assert {"sess_a", "sess_b"} <= ids
