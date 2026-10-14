"""Chunking strategies."""
from __future__ import annotations

import pytest

from app.services.chunking import chunk_fixed, chunk_sentences, chunk_text


def test_fixed_window_with_overlap():
    text = "abcdefghij" * 10  # 100 chars
    chunks = chunk_fixed(text, max_chars=30, overlap=10)
    assert chunks, "should produce chunks"
    assert all(len(c.content) <= 30 for c in chunks)
    # ordinals sequential
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_fixed_empty_text():
    assert chunk_fixed("   ", max_chars=10) == []


def test_sentence_packing_respects_max():
    text = "One sentence here. Another one follows. And a third shorter. " * 3
    chunks = chunk_sentences(text, max_chars=60)
    assert all(len(c.content) <= 60 for c in chunks)
    # every sentence kept somewhere
    joined = " ".join(c.content for c in chunks)
    assert "One sentence here." in joined


def test_long_sentence_is_subsplit():
    monster = "word " * 300  # one 'sentence' with no terminator, 1500 chars
    chunks = chunk_sentences(monster.strip(), max_chars=100)
    assert all(len(c.content) <= 100 for c in chunks)


def test_dispatch_strategy():
    assert chunk_text("hello world", strategy="fixed", max_chars=5)
    assert chunk_text("hi there.", strategy="sentence")
    with pytest.raises(ValueError):
        chunk_text("x", strategy="bogus")
