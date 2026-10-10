"""Pluggable experiment trackers (MLflow / JSONL / no-op)."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, Optional


class NullTracker:
    """Does nothing; keeps call sites unconditional."""

    kind = "null"

    @contextmanager
    def run(self, name: str, params: Optional[Dict] = None) -> Iterator[None]:
        yield

    def log_params(self, params: Dict) -> None:
        pass

    def log_metrics(self, metrics: Dict, step: Optional[int] = None) -> None:
        pass


class JsonlTracker(NullTracker):
    """Appends runs/metrics to a JSONL file — zero-dependency tracking."""

    kind = "jsonl"

    def __init__(self, path: str = "experiments.jsonl") -> None:
        self.path = Path(path)
        self._run_name: Optional[str] = None

    def _write(self, record: Dict) -> None:
        record["ts"] = time.time()
        record["run"] = self._run_name
        with self.path.open("a") as fh:
            fh.write(json.dumps(record) + "\n")

    @contextmanager
    def run(self, name: str, params: Optional[Dict] = None) -> Iterator[None]:
        self._run_name = name
        self._write({"event": "run_start", "params": params or {}})
        try:
            yield
        finally:
            self._write({"event": "run_end"})
            self._run_name = None

    def log_params(self, params: Dict) -> None:
        self._write({"event": "params", "params": params})

    def log_metrics(self, metrics: Dict, step: Optional[int] = None) -> None:
        self._write({"event": "metrics", "metrics": metrics, "step": step})


class MLflowTracker(NullTracker):
    """MLflow-backed tracker (requires `pip install 'tiles[telemetry]'`)."""

    kind = "mlflow"

    def __init__(self, experiment: str = "tiles") -> None:
        import mlflow  # noqa: F401 — fail fast if missing

        self._mlflow = mlflow
        mlflow.set_experiment(experiment)

    @contextmanager
    def run(self, name: str, params: Optional[Dict] = None) -> Iterator[None]:
        with self._mlflow.start_run(run_name=name):
            if params:
                self.log_params(params)
            yield

    def log_params(self, params: Dict) -> None:
        self._mlflow.log_params(
            {k: str(v)[:250] for k, v in params.items()}
        )

    def log_metrics(self, metrics: Dict, step: Optional[int] = None) -> None:
        self._mlflow.log_metrics(
            {k: float(v) for k, v in metrics.items()}, step=step
        )


def get_tracker(
    backend: str = "auto", **kwargs
) -> NullTracker:
    """``auto`` prefers MLflow when installed, else JSONL."""
    if backend == "mlflow":
        return MLflowTracker(**kwargs)
    if backend == "jsonl":
        return JsonlTracker(**kwargs)
    if backend == "null":
        return NullTracker()
    # auto
    try:
        return MLflowTracker(**kwargs)
    except ImportError:
        return JsonlTracker()
