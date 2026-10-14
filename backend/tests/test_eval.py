"""Eval scoring metrics."""
from __future__ import annotations

from eval.scoring import answer_relevancy, faithfulness, recall_at_k, score_case


def test_recall_at_k_counts_expected_terms_in_context():
    ctx = "The mitochondria is the powerhouse of the cell."
    assert recall_at_k(["mitochondria", "powerhouse"], ctx) == 1.0
    assert recall_at_k(["mitochondria", "banana"], ctx) == 0.5
    assert recall_at_k([], ctx) == 1.0


def test_answer_relevancy_overlap():
    assert answer_relevancy("the answer is Paris", "Paris") == 1.0
    assert answer_relevancy("totally unrelated", "Paris") == 0.0


def test_faithfulness_grounding():
    ans = "mitochondria produces ATP"
    ctx = "The mitochondria generates ATP energy"
    assert faithfulness(ans, ctx) > 0.3  # most tokens grounded
    assert faithfulness("quantum banana", ctx) < 0.5


def test_score_case_shape():
    s = score_case("q", ["a"], "a b", "a b c", "a b context")
    assert set(s) == {"recall_at_k", "answer_relevancy", "faithfulness"}
    assert 0.0 <= s["recall_at_k"] <= 1.0
