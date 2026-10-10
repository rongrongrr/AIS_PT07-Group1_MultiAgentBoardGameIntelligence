"""Rule-extraction benchmark (A5): RAG-to-Logic accuracy.

Runs the rulebook ingestion pipeline (rulebook.md → retrieval →
RuleSpecs) and verifies every extracted rule against the deterministic
engine as ground truth.
"""

from __future__ import annotations

import os

from tiles.experiments.registry import ExperimentSpec, ParamSpec
from tiles.rulebook import (
    RulebookIndex,
    extract_rules_deterministic,
    extract_rules_llm,
    verify_rules,
)

from ._common import bar, pct, result, table


def run(params: dict, ctx) -> dict:
    ctx.progress(0, 3, "indexing rulebook")
    index = RulebookIndex.build()
    requested = params["extractor"]
    used = "deterministic"
    note = ""
    ctx.progress(1, 3, f"extracting rules ({requested})")
    if requested == "llm":
        if os.environ.get("ANTHROPIC_API_KEY"):
            specs = extract_rules_llm(index)
            used = "llm"
            note = (
                " The LLM extractor was used (it silently falls back to the "
                "deterministic extractor on any API failure)."
            )
        else:
            specs = extract_rules_deterministic(index)
            note = (
                " LLM extraction was requested but ANTHROPIC_API_KEY is not set; "
                "the deterministic extractor ran instead."
            )
            ctx.log("ANTHROPIC_API_KEY not set; falling back to deterministic extraction", "warning")
    else:
        specs = extract_rules_deterministic(index)
    ctx.progress(2, 3, f"verifying {len(specs)} rules against the engine")
    report = verify_rules(specs)
    checks = {c.rule_id: c for c in report.checks}
    skipped = set(report.skipped)

    rows = []
    for spec in specs:
        if spec.id in checks:
            status = "verified" if checks[spec.id].ok else "mismatch"
            detail = checks[spec.id].detail
        elif spec.id in skipped:
            status, detail = "skipped", "no checker registered"
        else:
            status, detail = "skipped", ""
        rows.append({
            "id": spec.id, "section": spec.section, "kind": spec.kind,
            "predicate": spec.predicate, "parameters": spec.parameters,
            "text": spec.text, "status": status, "detail": detail,
        })
    counts = {
        "verified": report.verified,
        "mismatch": len(report.mismatches),
        "skipped": len(report.skipped),
    }
    ctx.progress(3, 3, "done")
    summary = (
        f"{used.capitalize()} extraction produced {len(specs)} rules; "
        f"{report.verified}/{len(report.checks)} verified against the engine "
        f"({pct(report.accuracy)} accuracy), {len(report.skipped)} skipped.{note}"
    )
    return result(
        summary=summary,
        metrics={
            "accuracy": report.accuracy,
            "verified": report.verified,
            "checked": len(report.checks),
            "skipped": len(report.skipped),
            "extracted": len(specs),
        },
        tables=[
            table("Extracted rules",
                  ["rule", "kind", "predicate", "section", "status", "detail"],
                  [[r["id"], r["kind"], r["predicate"] or "", r["section"], r["status"], r["detail"]]
                   for r in rows]),
        ],
        series=[
            bar("Verification outcome", list(counts),
                {"rules": list(counts.values())}, x_label="status", y_label="rules"),
        ],
        raw={"extractor_requested": requested, "extractor_used": used, "rules": rows,
             "params": dict(params)},
    )


SPEC = ExperimentSpec(
    name="rule_extraction",
    title="Rule-extraction benchmark",
    description=(
        "Extracts structured rules from the English rulebook (retrieval + "
        "parsing, or an LLM) and verifies each one against the deterministic "
        "rules engine."
    ),
    report_section="3. Rule ingestion (A5)",
    estimated="< 5 s (deterministic)",
    params=(
        ParamSpec("extractor", "str", "deterministic", "Extraction path",
                  choices=("deterministic", "llm")),
    ),
    run=run,
)
