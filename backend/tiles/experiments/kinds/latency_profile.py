"""Latency telemetry (A7): per-node timing distributions from the ledger.

Reads every recorded TurnRecord and summarizes decide / validate /
explain / total milliseconds per tactician (p50, p90, max) — the
evidence behind "orchestrated under latency considerations".
"""

from __future__ import annotations

from typing import Dict, List

from tiles.experiments.registry import ExperimentSpec, ParamSpec

from ._common import bar, percentile, result, table

TIMING_KEYS = ("decide_ms", "validate_ms", "explain_ms", "total_ms")


def run(params: dict, ctx) -> dict:
    wanted = (params.get("tactician") or "").strip()
    per_tactician: Dict[str, Dict[str, List[float]]] = {}
    sessions = set()
    n_moves = 0
    for session_id, record in ctx.ledger.iter_all_moves():
        tactician = record.get("tactician") or "unknown"
        if wanted and tactician != wanted:
            continue
        timing = record.get("timing") or {}
        bucket = per_tactician.setdefault(
            tactician, {key: [] for key in TIMING_KEYS}
        )
        for key in TIMING_KEYS:
            value = timing.get(key)
            if isinstance(value, (int, float)):
                bucket[key].append(float(value))
        sessions.add(session_id)
        n_moves += 1
    ctx.progress(1, 1, f"{n_moves} moves from {len(sessions)} sessions")

    if n_moves == 0:
        return result(
            summary=(
                "The ledger holds no recorded moves"
                + (f" for tactician {wanted!r}" if wanted else "")
                + "; play a session first (locally or live) and re-run."
            ),
            metrics={"moves": 0, "sessions": 0},
            raw={"params": dict(params)},
        )

    names = sorted(per_tactician)
    rows = []
    metrics: Dict[str, float] = {"moves": n_moves, "sessions": len(sessions)}
    stats: Dict[str, dict] = {}
    for name in names:
        bucket = per_tactician[name]
        entry = {"moves": len(bucket["decide_ms"]) or len(bucket["total_ms"])}
        for key in TIMING_KEYS:
            values = bucket[key]
            entry[key] = {
                "p50": round(percentile(values, 0.5), 2),
                "p90": round(percentile(values, 0.9), 2),
                "max": round(max(values), 2) if values else 0.0,
                "n": len(values),
            }
        stats[name] = entry
        metrics[f"decide_p50_{name}"] = entry["decide_ms"]["p50"]
        metrics[f"decide_p90_{name}"] = entry["decide_ms"]["p90"]
        metrics[f"total_p50_{name}"] = entry["total_ms"]["p50"]
        rows.append([
            name, entry["moves"],
            entry["decide_ms"]["p50"], entry["decide_ms"]["p90"], entry["decide_ms"]["max"],
            entry["validate_ms"]["p50"], entry["explain_ms"]["p50"],
            entry["total_ms"]["p50"], entry["total_ms"]["p90"],
        ])

    slowest = max(names, key=lambda n: stats[n]["decide_ms"]["p50"])
    fastest = min(names, key=lambda n: stats[n]["decide_ms"]["p50"])
    summary = (
        f"{n_moves} moves across {len(sessions)} sessions and {len(names)} tacticians. "
        f"Median decision time ranges from {stats[fastest]['decide_ms']['p50']:.1f} ms "
        f"({fastest}) to {stats[slowest]['decide_ms']['p50']:.1f} ms ({slowest}, "
        f"p90 {stats[slowest]['decide_ms']['p90']:.1f} ms); validation and explanation "
        f"stay under {max(stats[n]['validate_ms']['p90'] for n in names):.2f} ms and "
        f"{max(stats[n]['explain_ms']['p90'] for n in names):.2f} ms (p90)."
    )
    return result(
        summary=summary,
        metrics=metrics,
        tables=[
            table("Per-tactician latency (ms)",
                  ["tactician", "moves", "decide p50", "decide p90", "decide max",
                   "validate p50", "explain p50", "total p50", "total p90"],
                  rows),
        ],
        series=[
            bar("Median decision latency", names,
                {"decide p50 (ms)": [stats[n]["decide_ms"]["p50"] for n in names]},
                x_label="tactician", y_label="ms"),
            bar("p90 decision latency", names,
                {"decide p90 (ms)": [stats[n]["decide_ms"]["p90"] for n in names]},
                x_label="tactician", y_label="ms"),
            bar("Median pipeline node latency", names,
                {key.replace("_ms", ""): [stats[n][key]["p50"] for n in names]
                 for key in ("decide_ms", "validate_ms", "explain_ms")},
                x_label="tactician", y_label="ms"),
        ],
        raw={"stats": stats, "sessions": sorted(sessions), "params": dict(params)},
    )


SPEC = ExperimentSpec(
    name="latency_profile",
    title="Latency profile",
    description=(
        "Per-tactician decide/validate/explain/total latency percentiles "
        "computed from every move recorded in the ledger."
    ),
    report_section="7. Evaluation (A7 latency telemetry)",
    estimated="< 5 s",
    params=(
        ParamSpec("tactician", "str", "", "Only include this tactician (blank = all)"),
    ),
    run=run,
)
