"""Immutable SQLite game ledger.

Every move is persisted with its full before/after board snapshot, the
tactician's search report, the explanation, and validation + timing
metadata (the TurnRecord from docs/API.md, stored verbatim as JSON).
Rows are never rewritten — the only mutable fields are the session
status/result columns and the per-player profile upsert.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id           TEXT PRIMARY KEY,
    mode         TEXT NOT NULL DEFAULT 'local',
    config_json  TEXT NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'created',
    created_at   TEXT NOT NULL,
    completed_at TEXT,
    result_json  TEXT
);
CREATE TABLE IF NOT EXISTS moves (
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    step        INTEGER NOT NULL,
    record_json TEXT NOT NULL,
    UNIQUE (session_id, step)
);
CREATE TABLE IF NOT EXISTS rounds (
    session_id  TEXT NOT NULL REFERENCES sessions(id),
    round       INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    UNIQUE (session_id, round)
);
CREATE TABLE IF NOT EXISTS profiles (
    session_id   TEXT NOT NULL REFERENCES sessions(id),
    player_index INTEGER NOT NULL,
    profile_json TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (session_id, player_index)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Ledger:
    """Thread-safe append-only store for sessions and moves."""

    def __init__(self, path: str | Path = "tiles.db") -> None:
        self.path = str(path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- sessions -------------------------------------------------------------

    def create_session(
        self,
        session_id: str,
        mode: str = "local",
        config: Optional[dict] = None,
        status: str = "created",
    ) -> None:
        with self._lock:
            # Idempotent: the server pre-registers sessions that the
            # MatchRunner then re-announces when the game actually starts.
            self._conn.execute(
                "INSERT INTO sessions (id, mode, config_json, status, created_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(id) DO UPDATE SET"
                " mode=excluded.mode, config_json=excluded.config_json,"
                " status=excluded.status",
                (session_id, mode, json.dumps(config or {}), status, _now()),
            )
            self._conn.commit()

    def set_status(self, session_id: str, status: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET status = ? WHERE id = ?",
                (status, session_id),
            )
            self._conn.commit()

    def finish_session(self, session_id: str, result: dict) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET status = 'completed', completed_at = ?,"
                " result_json = ? WHERE id = ?",
                (_now(), json.dumps(result), session_id),
            )
            self._conn.commit()

    def get_session(self, session_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return self._session_row(row) if row else None

    def list_sessions(self) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC"
            ).fetchall()
        return [self._session_row(r) for r in rows]

    @staticmethod
    def _session_row(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "mode": row["mode"],
            "config": json.loads(row["config_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
            "result": json.loads(row["result_json"])
            if row["result_json"]
            else None,
        }

    # -- moves / rounds / profiles ---------------------------------------------

    def record_move(self, session_id: str, record: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO moves (session_id, step, record_json) VALUES (?, ?, ?)",
                (session_id, int(record["step"]), json.dumps(record)),
            )
            self._conn.commit()

    def record_round(self, session_id: str, round_number: int, result: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO rounds (session_id, round, result_json) VALUES (?, ?, ?)",
                (session_id, round_number, json.dumps(result)),
            )
            self._conn.commit()

    def save_profiles(self, session_id: str, profiles: List[dict]) -> None:
        now = _now()
        with self._lock:
            for profile in profiles:
                self._conn.execute(
                    "INSERT INTO profiles (session_id, player_index, profile_json, updated_at)"
                    " VALUES (?, ?, ?, ?)"
                    " ON CONFLICT (session_id, player_index)"
                    " DO UPDATE SET profile_json = excluded.profile_json,"
                    " updated_at = excluded.updated_at",
                    (
                        session_id,
                        int(profile["player_index"]),
                        json.dumps(profile),
                        now,
                    ),
                )
            self._conn.commit()

    def get_history(self, session_id: str) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT record_json FROM moves WHERE session_id = ? ORDER BY step",
                (session_id,),
            ).fetchall()
        return [json.loads(r["record_json"]) for r in rows]

    def get_profiles(self, session_id: str) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT profile_json FROM profiles WHERE session_id = ?"
                " ORDER BY player_index",
                (session_id,),
            ).fetchall()
        return [json.loads(r["profile_json"]) for r in rows]

    def get_rounds(self, session_id: str) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT result_json FROM rounds WHERE session_id = ? ORDER BY round",
                (session_id,),
            ).fetchall()
        return [json.loads(r["result_json"]) for r in rows]

    # -- export ----------------------------------------------------------------

    def export(self, session_id: str) -> dict:
        session = self.get_session(session_id)
        if session is None:
            raise KeyError(f"unknown session {session_id!r}")
        return {
            "session": session,
            "rounds": self.get_rounds(session_id),
            "moves": self.get_history(session_id),
            "profiles": self.get_profiles(session_id),
        }
