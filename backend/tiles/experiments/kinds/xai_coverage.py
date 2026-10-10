"""Explainability audit (A6 companion): coverage and faithfulness.

Reads every recorded move and measures (a) how many decisions carry an
explanation, (b) which concept tags appear, and (c) whether each
explanation's stated primary driver agrees with the search artifacts it
claims to summarize — i.e. the explanation is *faithful* to the
Tactician's own component breakdown, not invented after the fact.
"""

from __future__ import annotations

from typing import Dict

from tiles.agents.explainer.templates import _primary_driver
from tiles.experiments.registry import ExperimentSpec, ParamSpec

from ._common import bar, pct, result, table


def _new_bucket() -> dict:
    return {"moves": 0, "explained": 0, "checked": 0, "faithful": 0,
            "concepts": {}, "drivers": {}}


def run(params: dict, ctx) -> dict:
    per_tactician: Dict[str, dict] = {}
    overall = _new_bucket()
    sessions = set()

    def add(bucket: dict, record: dict) -> None:
        bucket["moves"] += 1
        explanation = record.get("explanation") or {}
        if not explanation.get("text"):
            return
        bucket["explained"] += 1
        for concept in explanation.get("concepts") or []:
            bucket["concepts"][concept] = bucket["concepts"].get(concept, 0) + 1
        evidence = explanation.get("evidence") or {}
        report = record.get("report") or {}
        candidates = report.get("candidates") or []
        notes = candidates[0].get("notes") if candidates else None
        claimed = evidence.get("primary_driver")
        if not notes or claimed is None:
            return
        numeric = {k: v for k, v in notes.items() if isinstance(v, (int, float))}
        expected = _primary_driver(numeric)
        bucket["checked"] += 1
        bucket["faithful"] += int(expected == claimed)
        bucket["drivers"][claimed] = bucket["drivers"].get(claimed, 0) + 1

    for session_id, record in ctx.ledger.iter_all_moves():
        sessions.add(session_id)
        tactician = record.get("tactician") or "unknown"
        add(per_tactician.setdefault(tactician, _new_bucket()), record)
        add(overall, record)
    ctx.progress(1, 1, f"{overall['moves']} moves audited")

    if overall["moves"] == 0:
        return result(
            summary="The ledger holds no recorded moves; play a session first and re-run.",
            metrics={"moves": 0},
            raw={"params": dict(params)},
        )

    def rate(num: int, den: int) -> float:
        return num / den if den else 0.0

    coverage = rate(overall["explained"], overall["moves"])
    faithfulness = rate(overall["faithful"], overall["checked"])
    concepts = dict(sorted(overall["concepts"].items(), key=lambda kv: -kv[1]))
    names = sorted(per_tactician)
    checked_names = [n for n in names if per_tactician[n]["checked"]]
    rows = []
    for name in names:
        b = per_tactician[name]
        rows.append([
            name, b["moves"], round(rate(b["explained"], b["moves"]), 3),
            b["checked"],
            round(rate(b["faithful"], b["checked"]), 3) if b["checked"] else "n/a",
            ", ".join(f"{c}:{n}" for c, n in sorted(b["concepts"].items(), key=lambda kv: -kv[1])[:4]),
        ])
    top_concept = next(iter(concepts), None)
    summary = (
        f"{pct(coverage)} of {overall['moves']} recorded moves carry an explanation; "
        f"{pct(faithfulness)} of the {overall['checked']} explanations with a stated primary "
        f"driver agree with the tactician's own score breakdown."
    )
    if top_concept:
        summary += f" Most common concept tag: {top_concept} ({concepts[top_concept]} moves)."
    return result(
        summary=summary,
        metrics={
            "moves": overall["moves"],
            "sessions": len(sessions),
            "coverage": coverage,
            "faithfulness": faithfulness,
            "checked": overall["checked"],
            "concept_tags": sum(concepts.values()),
        },
        tables=[
            table("Per-tactician explainability",
                  ["tactician", "moves", "coverage", "checked", "faithfulness", "top concepts"],
                  rows),
            table("Concept tag frequency", ["concept", "moves"],
                  [[c, n] for c, n in concepts.items()]),
            table("Stated primary driver", ["driver", "explanations"],
                  [[d, n] for d, n in sorted(overall["drivers"].items(), key=lambda kv: -kv[1])]),
        ],
        series=[
            bar("Concept tags across all explanations", list(concepts),
                {"moves": list(concepts.values())}, x_label="concept", y_label="moves"),
            bar("Explanation coverage by tactician", names,
                {"coverage": [rate(per_tactician[n]["explained"], per_tactician[n]["moves"]) for n in names]},
                x_label="tactician", y_label="rate"),
            bar("Faithfulness of the stated primary driver (tacticians that state one)",
                checked_names,
                {"faithfulness": [rate(per_tactician[n]["faithful"], per_tactician[n]["checked"])
                                  for n in checked_names]},
                x_label="tactician", y_label="rate"),
        ],
        raw={"per_tactician": per_tactician, "overall": overall,
             "sessions": sorted(sessions), "params": dict(params)},
    )


SPEC = ExperimentSpec(
    name="xai_coverage",
    title="Explainability audit",
    description=(
        "Coverage and faithfulness of the Explainer over every recorded "
        "move: how many decisions are explained, which concept tags appear, "
        "and whether stated drivers match the search artifacts."
    ),
    report_section="6. Explainability (A6 companion)",
    estimated="< 5 s",
    params=(
        ParamSpec("tactician", "str", "", "Reserved: filter (blank = all tacticians)"),
    ),
    run=run,
)
