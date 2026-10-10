"""End to end: rulebook text -> retrieved passages -> structured rules -> validated -> RulesConfig."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from tiles.azul.config import DEFAULT_RULES, RulesConfig
from tiles.rules_ingest.extract import PatternExtractor
from tiles.rules_ingest.schema import RuleSet, compare, ground_truth, to_config, wall_matches_standard


@dataclass
class IngestionResult:
    ruleset: RuleSet
    evidence: Dict[str, str]
    config: Optional[RulesConfig]          # None if the rulebook did not yield what the engine needs
    missing: List[str] = field(default_factory=list)
    wall_matches_standard: bool = False
    field_matches: Dict[str, bool] = field(default_factory=dict)   # vs the engine's built-in rules

    @property
    def matches_engine(self) -> bool:
        return all(self.field_matches.values()) and self.wall_matches_standard

    @property
    def differences_from_standard(self) -> List[str]:
        return [f for f, ok in self.field_matches.items() if not ok]


def ingest_text(text: str, extractor=None) -> IngestionResult:
    extractor = extractor or PatternExtractor()
    rs, evidence = extractor.extract(text)
    try:
        config: Optional[RulesConfig] = to_config(rs, strict=True)
        missing: List[str] = []
    except ValueError as e:
        config, missing = None, str(e).split(": ", 1)[1].split(", ")
    return IngestionResult(
        ruleset=rs, evidence=evidence, config=config, missing=missing,
        wall_matches_standard=wall_matches_standard(rs),
        field_matches=compare(rs, ground_truth()),
    )


def ingest_file(path: str | Path, extractor=None) -> IngestionResult:
    return ingest_text(Path(path).read_text(encoding="utf-8"), extractor)
