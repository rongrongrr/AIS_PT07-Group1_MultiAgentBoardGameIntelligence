"""Immutable SQLite game ledger.

Every move is persisted with its full before/after board snapshot, the
tactician's search report, the explanation, and validation + timing
metadata (the TurnRecord from docs/API.md, stored verbatim as JSON).
Rows are never rewritten — the only mutable fields are the session
status/result columns, the per-player profile upsert, and experiment
progress/result columns.

The ledger is the canonical store for *everything* the platform
produces: sessions (local and live), moves, round results, player
profiles, and experiment runs. Analysis, replay, dashboards, and
experiments all read from here.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

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
CREATE TABLE IF NOT EXISTS experiments (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    params_json   TEXT NOT NULL DEFAULT '{}',
    status        TEXT NOT NULL DEFAULT 'created',
    created_at    TEXT NOT NULL,
    completed_at  TEXT,
    progress_json TEXT,
    result_json   TEXT,
    error         TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Ledger:
    """Thread-safe append-only store for sessions, moves and experiments."""

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
            completed = (
                ", completed_at = ?"
                if status in ("completed", "aborted", "failed", "stalled")
                else ""
            )
            params: tuple = (status,)
            if completed:
                params = (status, _now())
            self._conn.execute(
                f"UPDATE sessions SET status = ?{completed} WHERE id = ?",
                params + (session_id,),
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

    def set_result(self, session_id: str, result: dict) -> None:
        """Attach a (partial) result without changing the status."""
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET result_json = ? WHERE id = ?",
                (json.dumps(result), session_id),
            )
            self._conn.commit()

    def get_session(self, session_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return self._session_row(row) if row else None

    def list_sessions(self, limit: Optional[int] = None) -> List[dict]:
        query = "SELECT * FROM sessions ORDER BY created_at DESC"
        if limit:
            query += f" LIMIT {int(limit)}"
        with self._lock:
            rows = self._conn.execute(query).fetchall()
        return [self._session_row(r) for r in rows]

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,)
            )
            for table in ("moves", "rounds", "profiles"):
                self._conn.execute(
                    f"DELETE FROM {table} WHERE session_id = ?", (session_id,)
                )
            self._conn.commit()
            return cur.rowcount > 0

    def count_moves(self, session_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS n FROM moves WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row["n"]) if row else 0

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
            # Plain INSERT on purpose: a step is written exactly once.
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

    def iter_all_moves(self):
        """Yield ``(session_id, record)`` for every recorded move
        (used by ledger-wide analyses such as latency profiling)."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id, record_json FROM moves ORDER BY session_id, step"
            ).fetchall()
        for row in rows:
            yield row["session_id"], json.loads(row["record_json"])

    def all_profiles(self) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT profile_json FROM profiles"
            ).fetchall()
        return [json.loads(r["profile_json"]) for r in rows]

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

    # -- experiments ------------------------------------------------------------

    def create_experiment(
        self, experiment_id: str, kind: str, params: Optional[dict] = None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO experiments (id, kind, params_json, status, created_at)"
                " VALUES (?, ?, ?, 'created', ?)",
                (experiment_id, kind, json.dumps(params or {}), _now()),
            )
            self._conn.commit()

    def update_experiment(
        self,
        experiment_id: str,
        status: Optional[str] = None,
        progress: Optional[dict] = None,
        result: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        sets: List[str] = []
        params: List[object] = []
        if status is not None:
            sets.append("status = ?")
            params.append(status)
            if status in ("completed", "failed", "aborted"):
                sets.append("completed_at = ?")
                params.append(_now())
        if progress is not None:
            sets.append("progress_json = ?")
            params.append(json.dumps(progress))
        if result is not None:
            sets.append("result_json = ?")
            params.append(json.dumps(result))
        if error is not None:
            sets.append("error = ?")
            params.append(error)
        if not sets:
            return
        params.append(experiment_id)
        with self._lock:
            self._conn.execute(
                f"UPDATE experiments SET {', '.join(sets)} WHERE id = ?",
                tuple(params),
            )
            self._conn.commit()

    def get_experiment(self, experiment_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM experiments WHERE id = ?", (experiment_id,)
            ).fetchone()
        return self._experiment_row(row) if row else None

    def list_experiments(self, with_result: bool = False) -> List[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM experiments ORDER BY created_at DESC"
            ).fetchall()
        out = [self._experiment_row(r) for r in rows]
        if not with_result:
            for item in out:
                item["result"] = None
        return out

    def delete_experiment(self, experiment_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM experiments WHERE id = ?", (experiment_id,)
            )
            self._conn.commit()
            return cur.rowcount > 0

    @staticmethod
    def _experiment_row(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "kind": row["kind"],
            "params": json.loads(row["params_json"] or "{}"),
            "status": row["status"],
            "created_at": row["created_at"],
            "completed_at": row["completed_at"],
            "progress": json.loads(row["progress_json"])
            if row["progress_json"]
            else {"done": 0, "total": 0, "message": ""},
            "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": row["error"],
        }

    # -- aggregate queries ----------------------------------------------------------

    def counts(self) -> Dict[str, Dict[str, int]]:
        """Row counts by status for sessions and experiments."""
        with self._lock:
            session_rows = self._conn.execute(
                "SELECT status, mode, COUNT(*) AS n FROM sessions GROUP BY status, mode"
            ).fetchall()
            experiment_rows = self._conn.execute(
                "SELECT status, COUNT(*) AS n FROM experiments GROUP BY status"
            ).fetchall()
            moves = self._conn.execute("SELECT COUNT(*) AS n FROM moves").fetchone()
        by_status: Dict[str, int] = {}
        by_mode: Dict[str, int] = {}
        for row in session_rows:
            by_status[row["status"]] = by_status.get(row["status"], 0) + row["n"]
            by_mode[row["mode"]] = by_mode.get(row["mode"], 0) + row["n"]
        return {
            "sessions_by_status": by_status,
            "sessions_by_mode": by_mode,
            "experiments_by_status": {r["status"]: r["n"] for r in experiment_rows},
            "moves_total": {"total": int(moves["n"]) if moves else 0},
        }
