"""Experiment tracking for tournaments and ablation studies.

MLflow is the report's chosen backbone but stays optional: the tracker
degrades to a JSONL file (and finally to a no-op) so experiments always
run.
"""

from .tracker import JsonlTracker, MLflowTracker, NullTracker, get_tracker

__all__ = ["get_tracker", "MLflowTracker", "JsonlTracker", "NullTracker"]
