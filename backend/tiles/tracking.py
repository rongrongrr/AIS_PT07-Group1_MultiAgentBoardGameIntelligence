"""Experiment tracking with MLflow (optional, never allowed to break a game).

* ``log_run`` records one run (params, metrics, tags, JSON artifacts, per-step series).
* ``log_session_run`` records a finished live game: configuration, final scores, per-model decision
  latency and the per-move telemetry (decision / click / websocket-wait / total ms), plus the full
  move ledger as an artifact.
* The evaluation scripts call ``log_run`` too (``--mlflow``), so tournaments and ablations land in
  the same place.

Tracking is a no-op if MLflow is not installed, if ``TILES_MLFLOW_DISABLED`` is set, or if logging
fails. The store defaults to a SQLite database in ``<repo>/mlruns`` (MLflow 3 no longer supports its
plain file store); set ``TILES_MLFLOW_URI`` (``sqlite:///...`` or an ``http://`` tracking server) to
change it.
"""

from __future__ import annotations

import json
import logging
import os
import statistics
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
# an unreachable tracking server must fail fast, not stall a game
os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")
os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "5")

DEFAULT_STORE = Path(__file__).resolve().parents[2] / "mlruns"
GAMES_EXPERIMENT = "tiles-games"
EVALUATION_EXPERIMENT = "tiles-evaluations"


def enabled() -> bool:
    return not os.environ.get("TILES_MLFLOW_DISABLED")


def tracking_uri() -> str:
    uri = os.environ.get("TILES_MLFLOW_URI")
    if uri:
        return uri
    DEFAULT_STORE.mkdir(parents=True, exist_ok=True)
    return "sqlite:///" + (DEFAULT_STORE / "mlflow.db").as_posix()


def _artifact_root(uri: str, experiment: str) -> Optional[str]:
    """Keep artifacts next to a sqlite store (MLflow would otherwise use ./mlruns in the cwd)."""
    if uri.startswith("sqlite:///"):
        return (Path(uri[len("sqlite:///"):]).parent / "artifacts" / experiment).as_uri()
    return None


def _mlflow():
    try:
        import mlflow
        return mlflow
    except Exception:
        return None


def log_run(experiment: str, run_name: str, params: Optional[Dict] = None, metrics: Optional[Dict[str, float]] = None,
            tags: Optional[Dict[str, str]] = None, artifacts: Optional[Dict[str, object]] = None,
            series: Optional[Dict[str, List[float]]] = None) -> Optional[str]:
    """Record one run; returns the MLflow run id, or None if tracking is off or failed."""
    if not enabled():
        return None
    ml = _mlflow()
    if ml is None:
        return None
    try:
        uri = tracking_uri()
        ml.set_tracking_uri(uri)
        if ml.get_experiment_by_name(experiment) is None:
            ml.create_experiment(experiment, artifact_location=_artifact_root(uri, experiment))
        ml.set_experiment(experiment)
        with ml.start_run(run_name=run_name) as run:
            if params:
                ml.log_params({k: str(v)[:500] for k, v in params.items()})
            if metrics:
                ml.log_metrics({k: float(v) for k, v in metrics.items() if v is not None})
            if tags:
                ml.set_tags({k: str(v) for k, v in tags.items()})
            for name, values in (series or {}).items():
                for step, v in enumerate(values):
                    ml.log_metric(name, float(v), step=step)
            for name, obj in (artifacts or {}).items():
                ml.log_dict(obj, f"{name}.json")
            return run.info.run_id
    except Exception:
        logger.exception("MLflow logging failed (ignored)")
        return None


def summarize_game(session: dict, moves: List[dict]) -> Dict:
    """Metrics and series for a finished game from its session row and move ledger (history format)."""
    metrics: Dict[str, float] = {"total_moves": len(moves)}
    scores = session.get("final_scores") or {}
    for name, sc in scores.items():
        metrics[f"final_score.{name}"] = sc
    if scores:
        ordered = sorted(scores.values(), reverse=True)
        metrics["winning_margin"] = ordered[0] - (ordered[1] if len(ordered) > 1 else 0)
    series: Dict[str, List[float]] = {}
    by_model: Dict[str, List[float]] = {}
    for key in ("decision_time_ms", "click_ms", "ws_wait_ms", "total_ms", "legal_actions"):
        vals = [m[key] for m in moves if m.get(key) is not None]
        if vals:
            metrics[f"avg_{key}"] = statistics.fmean(vals)
            metrics[f"max_{key}"] = max(vals)
            series[key] = vals
    for m in moves:
        if m.get("decision_time_ms") is not None:
            by_model.setdefault(m.get("system_tag") or "unknown", []).append(m["decision_time_ms"])
    for model, vals in by_model.items():
        metrics[f"avg_decision_ms.{model}"] = statistics.fmean(vals)
    floor_moves = [m for m in moves if m["action"]["destination"] == "floor"]
    metrics["floor_move_share"] = len(floor_moves) / len(moves) if moves else 0.0
    metrics["floor_fallbacks"] = sum(1 for m in moves if m.get("fell_back_to_floor"))
    return {"metrics": metrics, "series": series}


def log_session_run(session_id: str) -> Optional[str]:
    """Load a finished session from the database and record it. Safe to call from a worker thread."""
    if not enabled() or _mlflow() is None:
        return None
    try:
        from tiles.models.db import Move, SessionLocal, Session

        db = SessionLocal()
        try:
            row = db.query(Session).filter(Session.id == session_id).first()
            if row is None:
                return None
            moves = []
            for m in db.query(Move).filter(Move.session_id == session_id).order_by(Move.step_id).all():
                data = json.loads(m.action_json)
                extra = data.pop("_extra", {})
                entry = {"step_id": m.step_id, "player_name": m.player_name, "system_tag": m.system_tag,
                         "action": data, "decision_time_ms": m.decision_time_ms}
                entry.update({k: v for k, v in extra.items() if k != "board"})
                moves.append(entry)
            session = {"final_scores": json.loads(row.final_scores) if row.final_scores else {}}
            players = json.loads(row.player_config)
            params = {
                "session_id": session_id, "room": row.room_name, "browser_mode": row.browser_mode,
                "players": ", ".join(f"{p.get('name')}={p['type']}" for p in players),
                "move_timeout_sec": row.move_timeout_sec, "status": row.status,
            }
            summary = summarize_game(session, moves)
            return log_run(
                GAMES_EXPERIMENT, f"{session_id}", params, summary["metrics"],
                tags={"status": row.status, "winner": row.winner or "", "n_players": len(players)},
                artifacts={"moves": moves, "final_scores": session["final_scores"]},
                series=summary["series"],
            )
        finally:
            db.close()
    except Exception:
        logger.exception("could not log session run (ignored)")
        return None
