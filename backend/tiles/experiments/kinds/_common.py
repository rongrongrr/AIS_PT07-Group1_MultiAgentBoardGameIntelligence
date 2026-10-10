"""Shared helpers for building the uniform ExperimentResult shape."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence


def table(title: str, columns: Sequence[str], rows: Sequence[Sequence]) -> dict:
    return {"title": title, "columns": list(columns), "rows": [list(r) for r in rows]}


def bar(
    title: str,
    labels: Sequence[str],
    data: Dict[str, Sequence[float]],
    x_label: str = "",
    y_label: str = "",
) -> dict:
    return {
        "title": title,
        "kind": "bar",
        "x_label": x_label,
        "y_label": y_label,
        "labels": [str(label) for label in labels],
        "data": [{"name": name, "values": list(values)} for name, values in data.items()],
    }


def line(
    title: str,
    labels: Sequence[str],
    data: Dict[str, Sequence[float]],
    x_label: str = "",
    y_label: str = "",
) -> dict:
    series = bar(title, labels, data, x_label, y_label)
    series["kind"] = "line"
    return series


def matrix(
    title: str,
    row_labels: Sequence[str],
    col_labels: Sequence[str],
    values: Sequence[Sequence[float]],
    x_label: str = "",
    y_label: str = "",
) -> dict:
    return {
        "title": title,
        "kind": "matrix",
        "x_label": x_label,
        "y_label": y_label,
        "labels": [str(label) for label in col_labels],
        "row_labels": [str(label) for label in row_labels],
        "data": [
            {"name": str(name), "values": list(row)}
            for name, row in zip(row_labels, values)
        ],
    }


def result(
    summary: str,
    metrics: Optional[Dict[str, float]] = None,
    tables: Optional[List[dict]] = None,
    series: Optional[List[dict]] = None,
    raw: Optional[dict] = None,
) -> dict:
    return {
        "summary": summary,
        "metrics": {k: _num(v) for k, v in (metrics or {}).items()},
        "tables": tables or [],
        "series": series or [],
        "raw": raw or {},
    }


def _num(value) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int):
        return value
    return round(float(value), 4)


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..1) of a non-empty sequence."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round(q * (len(ordered) - 1)))
    return float(ordered[max(0, min(index, len(ordered) - 1))])


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def pct(value: float) -> str:
    return f"{value:.0%}"


def abort_note(ctx) -> str:
    """Prefix for summaries of runs that were stopped early."""
    return "Stopped early (partial results). " if ctx.stopped() else ""
