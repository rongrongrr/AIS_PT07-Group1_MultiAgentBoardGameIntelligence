"""Rulebook ingestion: chunking + a pure-Python TF-IDF retriever.

First stage of the RAG-to-Logic pipeline: the natural-language rulebook
is split into section-level and sentence-window chunks, indexed with
TF-IDF, and retrieved by cosine similarity. No numpy/sklearn — the
corpus is one rulebook, so a dict-based sparse index is plenty.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Tuple

DEFAULT_RULEBOOK_PATH = Path(__file__).parent / "rulebook.md"

_HEADING_RE = re.compile(r"^#{1,3}\s+(?P<title>.*?)\s*\{#(?P<id>[a-z0-9-]+)\}\s*$")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "the a an of to and is are in on or for be it that this with from "
    "you your as at by may not no if then they their them its each "
    "into onto all any one two also".split()
)

# Sliding-window parameters (sentences per chunk / stride).
_WINDOW = 3
_STRIDE = 2


@dataclass(frozen=True)
class Chunk:
    text: str
    section: str
    score: float = 0.0


def _tokenize(text: str) -> List[str]:
    return [
        t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS
    ]


def _sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+", " ".join(text.split()))
    return [p.strip() for p in parts if p.strip()]


def _split_sections(markdown: str) -> List[Tuple[str, str]]:
    """Split by ``{#id}``-anchored headings into (section_id, body)."""
    sections: List[Tuple[str, List[str]]] = []
    current_id = None
    for line in markdown.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            current_id = match.group("id")
            sections.append((current_id, []))
        elif current_id is not None:
            sections[-1][1].append(line)
    return [
        (sid, "\n".join(body).strip())
        for sid, body in sections
        if "\n".join(body).strip()
    ]


class RulebookIndex:
    """TF-IDF index over rulebook chunks."""

    def __init__(self, chunks: List[Chunk]) -> None:
        self.chunks = chunks
        self._doc_freq: Dict[str, int] = {}
        token_lists = [_tokenize(c.text) for c in chunks]
        for tokens in token_lists:
            for term in set(tokens):
                self._doc_freq[term] = self._doc_freq.get(term, 0) + 1
        n = len(chunks)
        self._idf = {
            term: math.log((1 + n) / (1 + df)) + 1.0
            for term, df in self._doc_freq.items()
        }
        self._vectors = [self._vectorize(tokens) for tokens in token_lists]

    # -- construction ---------------------------------------------------

    @classmethod
    def build(cls, path: Path | str = DEFAULT_RULEBOOK_PATH) -> "RulebookIndex":
        markdown = Path(path).read_text(encoding="utf-8")
        chunks: List[Chunk] = []
        for section_id, body in _split_sections(markdown):
            body_flat = " ".join(body.split())
            chunks.append(Chunk(text=body_flat, section=section_id))
            sentences = _sentences(body)
            if len(sentences) > _WINDOW:
                for i in range(0, len(sentences) - 1, _STRIDE):
                    window = " ".join(sentences[i : i + _WINDOW])
                    if window and window != body_flat:
                        chunks.append(Chunk(text=window, section=section_id))
        return cls(chunks)

    # -- retrieval --------------------------------------------------------

    def _vectorize(self, tokens: List[str]) -> Dict[str, float]:
        if not tokens:
            return {}
        counts: Dict[str, int] = {}
        for t in tokens:
            counts[t] = counts.get(t, 0) + 1
        vec = {
            term: (count / len(tokens)) * self._idf.get(term, 1.0)
            for term, count in counts.items()
        }
        norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
        return {term: w / norm for term, w in vec.items()}

    def search(self, query: str, k: int = 5) -> List[Chunk]:
        """Top-``k`` chunks by cosine similarity, best first."""
        qvec = self._vectorize(_tokenize(query))
        scored = []
        for chunk, dvec in zip(self.chunks, self._vectors):
            small, large = (qvec, dvec) if len(qvec) < len(dvec) else (dvec, qvec)
            sim = sum(w * large.get(term, 0.0) for term, w in small.items())
            if sim > 0:
                scored.append(replace(chunk, score=sim))
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:k]

    def full_text(self) -> str:
        """Concatenated section chunks (for whole-rulebook LLM prompts)."""
        seen = set()
        parts = []
        for chunk in self.chunks:
            if chunk.section not in seen:
                seen.add(chunk.section)
                parts.append(f"[{chunk.section}] {chunk.text}")
        return "\n\n".join(parts)
