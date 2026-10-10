"""Dashboard aggregates over the ledger (docs/API.md "Stats")."""

from __future__ import annotations

from typing import Dict, List

from tiles.ledger.store import Ledger

_TIMING_KEYS = ("decide_ms", "validate_ms", "explain_ms", "total_ms")


def _percentile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return round(ordered[idx], 2)


def compute_stats(ledger: Ledger, session_summaries: List[dict], recent: int = 8) -> dict:
    counts = ledger.counts()

    per_tactician: Dict[str, dict] = {}
    for summary in session_summaries:
        scores = summary.get("scores")
        if not scores:
            continue
        winner = summary.get("winner")
        for i, player in enumerate(summary.get("players") or []):
            name = player.get("tactician", "?")
            entry = per_tactician.setdefault(
                name, {"games": 0, "wins": 0, "score_sum": 0, "decide": []}
            )
            entry["games"] += 1
            entry["wins"] += int(winner == i)
            if i < len(scores):
                entry["score_sum"] += scores[i]

    latency: Dict[str, List[float]] = {k: [] for k in _TIMING_KEYS}
    for _session_id, record in ledger.iter_all_moves():
        timing = record.get("timing") or {}
        for key in _TIMING_KEYS:
            if timing.get(key) is not None:
                latency[key].append(float(timing[key]))
        tactician = record.get("tactician")
        if tactician in per_tactician and timing.get("decide_ms") is not None:
            per_tactician[tactician]["decide"].append(float(timing["decide_ms"]))

    tacticians = []
    for name, entry in sorted(per_tactician.items()):
        games = entry["games"]
        tacticians.append(
            {
                "name": name,
                "games": games,
                "wins": entry["wins"],
                "win_rate": round(entry["wins"] / games, 3) if games else 0.0,
                "avg_score": round(entry["score_sum"] / games, 1) if games else 0.0,
                "avg_decide_ms": round(
                    sum(entry["decide"]) / len(entry["decide"]), 2
                )
                if entry["decide"]
                else 0.0,
            }
        )

    archetypes: Dict[str, int] = {}
    for profile in ledger.all_profiles():
        name = profile.get("archetype")
        if name:
            archetypes[name] = archetypes.get(name, 0) + 1

    return {
        "sessions": {
            "total": sum(counts["sessions_by_status"].values()),
            "by_status": counts["sessions_by_status"],
            "by_mode": counts["sessions_by_mode"],
        },
        "moves_total": counts["moves_total"]["total"],
        "experiments": {
            "total": sum(counts["experiments_by_status"].values()),
            "by_status": counts["experiments_by_status"],
        },
        "tacticians": tacticians,
        "archetypes": archetypes,
        "latency": {
            key: {
                "n": len(values),
                "p50": _percentile(values, 0.5),
                "p90": _percentile(values, 0.9),
                "max": round(max(values), 2) if values else 0.0,
            }
            for key, values in latency.items()
        },
        "recent_sessions": session_summaries[:recent],
    }
