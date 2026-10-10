"""TILES rulebook module: RAG-to-Logic rule ingestion.

Pipeline: rulebook.md (natural language) → RulebookIndex (TF-IDF
retrieval) → RuleSpec extraction (deterministic or LLM-backed) →
verification against the deterministic engine (the accuracy benchmark).
"""

from .extract import (
    ENGINE_PREDICATES,
    RuleSpec,
    extract_rules_deterministic,
    extract_rules_llm,
)
from .ingest import Chunk, RulebookIndex
from .verify import VerificationReport, verify_rules

__all__ = [
    "Chunk",
    "RulebookIndex",
    "RuleSpec",
    "ENGINE_PREDICATES",
    "extract_rules_deterministic",
    "extract_rules_llm",
    "VerificationReport",
    "verify_rules",
]
