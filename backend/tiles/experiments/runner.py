"""Experiment execution: background runs, progress, persistence, events.

:class:`ExperimentManager` is the single owner of experiment runs for a
server process. Each run executes a kind's ``run(params, ctx)`` on a
daemon thread; the :class:`ExperimentContext` handed to it reports
progress, exposes the ledger, and answers ``stopped()`` so long runs
can abort between games. Everything a run produces is persisted in the
ledger's ``experiments`` table (progress, result, error) and mirrored
as WebSocket-shaped events (``status`` / ``progress`` / ``log`` /
``result``, docs/API.md) to subscribers.
"""

from __future__ import annotations

import asyncio
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from tiles.ledger.store import Ledger

from .registry import ExperimentSpec, get_spec, validate_params

EVENT_BUFFER = 500
_PERSIST_INTERVAL_S = 0.5
TERMINAL = ("completed", "failed", "aborted")


@dataclass
class _Run:
    id: str
    spec: ExperimentSpec
    params: dict
    status: str = "created"
    progress: dict = field(
        default_factory=lambda: {"done": 0, "total": 0, "message": ""}
    )
    result: Optional[dict] = None
    error: Optional[str] = None
    events: List[dict] = field(default_factory=list)
    subscribers: List[asyncio.Queue] = field(default_factory=list)
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None
    last_persist: float = 0.0


class ExperimentContext:
    """What a running experiment can see and do."""

    def __init__(self, manager: "ExperimentManager", run: _Run) -> None:
        self._manager = manager
        self._run = run
        self.ledger: Ledger = manager.ledger
        self.params = run.params

    @property
    def run_id(self) -> str:
        return self._run.id

    def progress(self, done: int, total: int, message: str = "") -> None:
        self._manager._progress(self._run, done, total, message)

    def stopped(self) -> bool:
        return self._run.stop_event.is_set()

    def log(self, message: str, level: str = "info") -> None:
        self._manager._publish(
            self._run, {"type": "log", "level": level, "message": message}
        )


class ExperimentManager:
    """Runs experiments, persists them, and fans events out."""

    def __init__(
        self,
        ledger: Ledger,
        on_event: Optional[Callable[[str, dict], None]] = None,
    ) -> None:
        self.ledger = ledger
        #: the server's running event loop (set at startup); used to hand
        #: events from worker threads to WebSocket subscriber queues.
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._on_event = on_event
        self._runs: Dict[str, _Run] = {}
        self._lock = threading.Lock()

    # -- public API ---------------------------------------------------------------

    def start(self, kind: str, params: Optional[dict] = None) -> dict:
        """Validate, persist, and launch ``kind`` on a daemon thread."""
        run = self._create(kind, params)
        run.thread = threading.Thread(
            target=self._execute, args=(run,), daemon=True, name=run.id
        )
        run.thread.start()
        return self.get(run.id)

    def run_sync(self, kind: str, params: Optional[dict] = None) -> dict:
        """Validate, persist, and run ``kind`` to completion (CLI/tests)."""
        run = self._create(kind, params)
        self._execute(run)
        return self.get(run.id)

    def get(self, experiment_id: str) -> Optional[dict]:
        row = self.ledger.get_experiment(experiment_id)
        if row is None:
            return None
        return self._merge(row)

    def list(self) -> List[dict]:
        return [self._merge(row) for row in self.ledger.list_experiments()]

    def stop(self, experiment_id: str) -> None:
        with self._lock:
            run = self._runs.get(experiment_id)
        if run is None:
            if self.ledger.get_experiment(experiment_id) is None:
                raise KeyError(experiment_id)
            return  # not running in this process; nothing to signal
        run.stop_event.set()

    def delete(self, experiment_id: str) -> bool:
        with self._lock:
            run = self._runs.get(experiment_id)
            if run is not None and run.status in ("created", "running"):
                raise ValueError("experiment is running; stop it first")
            self._runs.pop(experiment_id, None)
        return self.ledger.delete_experiment(experiment_id)

    def subscribe(
        self, experiment_id: str, replay: bool = True
    ) -> asyncio.Queue:
        """Queue of future events for ``experiment_id``. With ``replay``
        the queue is pre-filled with the buffered history, atomically
        with the subscription, so nothing is missed or duplicated."""
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            run = self._runs.get(experiment_id)
            history = (
                list(run.events)
                if run is not None
                else self._synthesized_events(experiment_id)
            )
            if replay:
                for event in history:
                    queue.put_nowait(event)
            if run is not None:
                run.subscribers.append(queue)
        return queue

    def unsubscribe(self, experiment_id: str, queue: asyncio.Queue) -> None:
        with self._lock:
            run = self._runs.get(experiment_id)
            if run is not None and queue in run.subscribers:
                run.subscribers.remove(queue)

    def buffered_events(self, experiment_id: str) -> List[dict]:
        with self._lock:
            run = self._runs.get(experiment_id)
            if run is not None:
                return list(run.events)
        return self._synthesized_events(experiment_id)

    def is_running(self, experiment_id: str) -> bool:
        with self._lock:
            run = self._runs.get(experiment_id)
        return run is not None and run.status in ("created", "running")

    def shutdown(self) -> None:
        with self._lock:
            runs = list(self._runs.values())
        for run in runs:
            run.stop_event.set()

    # -- internals ------------------------------------------------------------------

    def _create(self, kind: str, params: Optional[dict]) -> _Run:
        spec = get_spec(kind)
        normalized = validate_params(kind, params)
        run = _Run(
            id=f"exp_{uuid.uuid4().hex[:12]}", spec=spec, params=normalized
        )
        self.ledger.create_experiment(run.id, kind, normalized)
        with self._lock:
            self._runs[run.id] = run
        return run

    def _merge(self, row: dict) -> dict:
        with self._lock:
            run = self._runs.get(row["id"])
        out = dict(row)
        try:
            out["title"] = get_spec(row["kind"]).title
        except ValueError:
            out["title"] = row["kind"]
        if run is not None:
            out["status"] = run.status
            out["progress"] = dict(run.progress)
            if run.error:
                out["error"] = run.error
        return out

    def _synthesized_events(self, experiment_id: str) -> List[dict]:
        """History for a run this process did not execute (e.g. finished
        before a restart): reconstruct status/progress/result rows."""
        row = self.ledger.get_experiment(experiment_id)
        if row is None:
            return []
        events: List[dict] = [{"type": "status", "status": row["status"]}]
        if row.get("progress"):
            events.append({"type": "progress", **row["progress"]})
        if row.get("error"):
            events.append(
                {"type": "log", "level": "error", "message": row["error"]}
            )
        if row.get("result") is not None:
            events.append({"type": "result", "result": row["result"]})
        return events

    def _publish(self, run: _Run, event: dict) -> None:
        with self._lock:
            run.events.append(event)
            if len(run.events) > EVENT_BUFFER:
                del run.events[: len(run.events) - EVENT_BUFFER]
            queues = list(run.subscribers)
        if self.loop is not None:
            for queue in queues:
                try:
                    self.loop.call_soon_threadsafe(queue.put_nowait, event)
                except RuntimeError:  # loop closed
                    pass
        if self._on_event is not None:
            try:
                self._on_event(run.id, event)
            except Exception:  # noqa: BLE001 — observers never break a run
                pass

    def _set_status(self, run: _Run, status: str) -> None:
        run.status = status
        self.ledger.update_experiment(run.id, status=status)
        self._publish(run, {"type": "status", "status": status})

    def _progress(self, run: _Run, done: int, total: int, message: str) -> None:
        run.progress = {"done": int(done), "total": int(total), "message": message}
        now = time.monotonic()
        if now - run.last_persist >= _PERSIST_INTERVAL_S or done >= total:
            run.last_persist = now
            self.ledger.update_experiment(run.id, progress=run.progress)
        self._publish(run, {"type": "progress", **run.progress})

    def _execute(self, run: _Run) -> None:
        self._set_status(run, "running")
        ctx = ExperimentContext(self, run)
        try:
            result = run.spec.run(run.params, ctx)
        except Exception as exc:  # surface, never kill the server
            run.error = f"{type(exc).__name__}: {exc}"
            self._publish(
                run,
                {
                    "type": "log",
                    "level": "error",
                    "message": run.error + "\n" + traceback.format_exc(limit=5),
                },
            )
            self.ledger.update_experiment(
                run.id, status="failed", error=run.error, progress=run.progress
            )
            run.status = "failed"
            self._publish(run, {"type": "status", "status": "failed"})
            return
        run.result = result
        status = "aborted" if run.stop_event.is_set() else "completed"
        if run.progress.get("total"):
            run.progress["done"] = (
                run.progress["total"] if status == "completed" else run.progress["done"]
            )
        self.ledger.update_experiment(
            run.id, status=status, result=result, progress=run.progress
        )
        self._publish(run, {"type": "result", "result": result})
        run.status = status
        self._publish(run, {"type": "status", "status": status})
