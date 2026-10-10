"""Chunking and TF-IDF retrieval over rulebook text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel


def split_sentences(text: str) -> List[str]:
    text = re.sub(r"\s+", " ", text.replace("\r", " ")).strip()
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", text) if s.strip()]


def chunk(text: str, window: int = 2) -> List[str]:
    """Overlapping windows of ``window`` sentences, per paragraph (headings dropped)."""
    chunks: List[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = "\n".join(l for l in para.splitlines() if not l.lstrip().startswith("#")).strip()
        if not para:
            continue
        sents = split_sentences(para)
        if len(sents) <= window:
            chunks.append(" ".join(sents))
            continue
        for i in range(len(sents) - window + 1):
            chunks.append(" ".join(sents[i:i + window]))
    return chunks


@dataclass
class Hit:
    score: float
    text: str


class Retriever:
    def __init__(self, chunks: List[str]):
        self.chunks = chunks
        self._vec = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True)
        self._matrix = self._vec.fit_transform(chunks) if chunks else None

    def query(self, q: str, k: int = 3) -> List[Hit]:
        if self._matrix is None:
            return []
        sims = linear_kernel(self._vec.transform([q]), self._matrix).ravel()
        order = sims.argsort()[::-1][:k]
        return [Hit(float(sims[i]), self.chunks[i]) for i in order if sims[i] > 0]
