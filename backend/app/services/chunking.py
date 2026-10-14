"""Text chunking for RAG ingestion.

Two strategies:
  - fixed:     sliding window by characters with overlap.
  - sentence:  split on sentence boundaries, then pack into <= max_chars blocks.

Returns Chunk objects carrying ordinal + the parent text. Kept dependency-free
and deterministic so ingestion is unit-testable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class Chunk:
    ordinal: int
    content: str


def chunk_fixed(text: str, *, max_chars: int = 800, overlap: int = 120) -> list[Chunk]:
    """Sliding-window chunking with overlap so context isn't cut at boundaries."""
    text = text.strip()
    if not text:
        return []
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    overlap = min(overlap, max_chars - 1)
    step = max_chars - overlap
    chunks: list[Chunk] = []
    i = 0
    ordinal = 0
    while i < len(text):
        window = text[i : i + max_chars].strip()
        if window:
            chunks.append(Chunk(ordinal, window))
            ordinal += 1
        i += step
    return chunks


def chunk_sentences(text: str, *, max_chars: int = 800) -> list[Chunk]:
    """Split into sentences, then greedily pack sentences into blocks <= max_chars."""
    text = text.strip()
    if not text:
        return []
    sentences = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
    chunks: list[Chunk] = []
    buf = ""
    ordinal = 0
    for s in sentences:
        if len(s) > max_chars:
            # a single huge sentence: flush buffer, then fixed-split the monster
            if buf:
                chunks.append(Chunk(ordinal, buf))
                ordinal += 1
                buf = ""
            for sub in chunk_fixed(s, max_chars=max_chars, overlap=0):
                chunks.append(Chunk(ordinal, sub.content))
                ordinal += 1
            continue
        candidate = (buf + " " + s).strip() if buf else s
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            chunks.append(Chunk(ordinal, buf))
            ordinal += 1
            buf = s
    if buf:
        chunks.append(Chunk(ordinal, buf))
    return chunks


def chunk_text(text: str, *, strategy: str = "sentence", max_chars: int = 800, overlap: int = 120) -> list[Chunk]:
    if strategy == "fixed":
        return chunk_fixed(text, max_chars=max_chars, overlap=overlap)
    if strategy == "sentence":
        return chunk_sentences(text, max_chars=max_chars)
    raise ValueError(f"unknown chunking strategy: {strategy}")
