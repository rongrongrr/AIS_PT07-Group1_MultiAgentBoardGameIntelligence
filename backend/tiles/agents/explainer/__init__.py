"""Explainer registry."""

from __future__ import annotations

from typing import Callable, Dict

from tiles.agents.base import Explainer

from .llm import LLMExplainer
from .templates import TemplateExplainer

EXPLAINERS: Dict[str, Callable[..., Explainer]] = {
    "template": TemplateExplainer,
    "llm": LLMExplainer,
}


def make_explainer(name: str, **kwargs) -> Explainer:
    try:
        factory = EXPLAINERS[name]
    except KeyError:
        raise ValueError(
            f"unknown explainer {name!r}; available: {sorted(EXPLAINERS)}"
        ) from None
    return factory(**kwargs)


__all__ = ["EXPLAINERS", "make_explainer", "TemplateExplainer", "LLMExplainer"]
