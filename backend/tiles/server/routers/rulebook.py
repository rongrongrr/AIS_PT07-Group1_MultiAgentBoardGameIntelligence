"""Rulebook RAG endpoints (docs/API.md "Rulebook").

The rulebook index is built once per process; extraction + verification
is cheap (milliseconds) for the deterministic path, so it runs per
request. The LLM path is only attempted when a key is configured and
always reports which extractor actually produced the specs.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Query

from tiles.rulebook import (
    RulebookIndex,
    extract_rules_deterministic,
    extract_rules_llm,
    verify_rules,
)
from tiles.rulebook.ingest import DEFAULT_RULEBOOK_PATH

router = APIRouter(prefix="/api/rulebook", tags=["rulebook"])

_HEADING_RE = re.compile(r"^#{1,3}\s+(?P<title>.*?)\s*\{#(?P<id>[a-z0-9-]+)\}\s*$")


@lru_cache(maxsize=1)
def _index() -> RulebookIndex:
    return RulebookIndex.build(DEFAULT_RULEBOOK_PATH)


@lru_cache(maxsize=1)
def _sections() -> list:
    sections = []
    current = None
    for line in Path(DEFAULT_RULEBOOK_PATH).read_text(encoding="utf-8").splitlines():
        match = _HEADING_RE.match(line)
        if match:
            current = {"id": match.group("id"), "title": match.group("title"), "lines": []}
            sections.append(current)
        elif current is not None:
            current["lines"].append(line)
    return [
        {"id": s["id"], "title": s["title"], "text": "\n".join(s["lines"]).strip()}
        for s in sections
    ]


@router.get("")
def rulebook() -> dict:
    return {"sections": _sections()}


@router.get("/search")
def search(q: str = Query(..., min_length=1), k: int = Query(5, ge=1, le=20)) -> dict:
    results = _index().search(q, k=k)
    return {
        "query": q,
        "results": [
            {"section": c.section, "text": c.text, "score": round(c.score, 4)}
            for c in results
        ],
    }


@router.get("/rules")
def rules(extractor: str = Query("deterministic")) -> dict:
    index = _index()
    used = "deterministic"
    if extractor == "llm" and os.environ.get("ANTHROPIC_API_KEY"):
        specs = extract_rules_llm(index)
        used = "llm"
    else:
        specs = extract_rules_deterministic(index)
    report = verify_rules(specs)
    status_by_id = {c.rule_id: ("verified" if c.ok else "mismatch", c.detail) for c in report.checks}
    for rule_id in report.skipped:
        status_by_id[rule_id] = ("skipped", "no checker registered")
    return {
        "extractor": used,
        "requested": extractor,
        "accuracy": round(report.accuracy, 4),
        "verified": report.verified,
        "checked": len(report.checks),
        "skipped": len(report.skipped),
        "rules": [
            {
                **spec.to_dict(),
                "status": status_by_id.get(spec.id, ("skipped", ""))[0],
                "detail": status_by_id.get(spec.id, ("", ""))[1],
            }
            for spec in specs
        ],
    }
