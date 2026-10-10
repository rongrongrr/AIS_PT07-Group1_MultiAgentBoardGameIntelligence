"""Rulebook ingestion: retrieve relevant passages, extract structured rules, validate them
against the engine, and turn them into a RulesConfig for the validator/simulator."""

from app.rules_ingest.extract import PatternExtractor, LLMExtractor  # noqa: F401
from app.rules_ingest.schema import FIELDS, RuleSet, compare, ground_truth, to_config  # noqa: F401
