"""Deterministic RAG eval metrics (no LLM-judge needed -> runnable in CI offline).

  - recall_at_k:      fraction of expected source terms present in retrieved context
                      (measures RETRIEVAL quality; the gate for CI in mock mode).
  - answer_relevancy: token-set overlap between answer and expected answer.
  - faithfulness:     fraction of answer tokens grounded in the retrieved context
                      (a cheap proxy for hallucination; higher = more grounded).

In LIVE mode you can additionally gate on an LLM-as-judge; these lexical metrics
give a fast, reproducible regression signal for CI.
"""
from __future__ import annotations

import re

_TOKEN = re.compile(r"[a-zA-Z0-9\u0E00-\u0E7F]+")


def tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def recall_at_k(expected_terms: list[str], retrieved_text: str) -> float:
    """How many expected source terms appear somewhere in the retrieved context."""
    if not expected_terms:
        return 1.0
    ctx = retrieved_text.lower()
    hit = sum(1 for term in expected_terms if term.lower() in ctx)
    return hit / len(expected_terms)


def answer_relevancy(answer: str, expected_answer: str) -> float:
    a, e = tokens(answer), tokens(expected_answer)
    if not e:
        return 1.0
    return len(a & e) / len(e)


def faithfulness(answer: str, context: str) -> float:
    a, c = tokens(answer), tokens(context)
    if not a:
        return 1.0
    return len(a & c) / len(a)


def score_case(question: str, expected_terms: list[str], expected_answer: str,
               answer: str, retrieved_text: str) -> dict[str, float]:
    return {
        "recall_at_k": round(recall_at_k(expected_terms, retrieved_text), 4),
        "answer_relevancy": round(answer_relevancy(answer, expected_answer), 4),
        "faithfulness": round(faithfulness(answer, retrieved_text), 4),
    }
