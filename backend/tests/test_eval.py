"""Eval scoring metrics + A/B comparison (from app.services.eval)."""
from __future__ import annotations

import pytest

from app.services.eval import (
    answer_relevancy,
    compare_prompts,
    faithfulness,
    load_golden,
    recall_at_k,
    run_suite,
    score_case,
)
from app.services.prompt_store import InMemoryPromptStore


def test_recall_at_k_counts_expected_terms_in_context():
    ctx = "The mitochondria is the powerhouse of the cell."
    assert recall_at_k(["mitochondria", "powerhouse"], ctx) == 1.0
    assert recall_at_k(["mitochondria", "banana"], ctx) == 0.5
    assert recall_at_k([], ctx) == 1.0


def test_answer_relevancy_and_faithfulness():
    assert answer_relevancy("the answer is Paris", "Paris") == 1.0
    assert answer_relevancy("totally unrelated", "Paris") == 0.0
    assert faithfulness("mitochondria produces ATP", "The mitochondria generates ATP energy") > 0.3


def test_score_case_shape():
    s = score_case(["a"], "a b", "a b c", "a b context")
    assert set(s) == {"recall_at_k", "answer_relevancy", "faithfulness"}


@pytest.mark.asyncio
async def test_run_suite_passes_recall_gate():
    rows = await run_suite(load_golden())
    assert len(rows) >= 5
    # retrieval should be perfect with the lexical mock embedder
    assert all(r["recall_at_k"] >= 0.8 for r in rows)


@pytest.mark.asyncio
async def test_compare_prompts_returns_ab():
    prompts = InMemoryPromptStore()
    # add a second version so we can compare v1 vs v2
    body2 = "Answer ONLY from context.\n{{context}}\nQ: {{question}}"
    await prompts.add(name="rag_default", body=body2, created_by="t")
    result = await compare_prompts(prompts, prompt_name="rag_default", version_a=1, version_b=2)
    assert result.version_a == 1 and result.version_b == 2
    assert len(result.cases) >= 5
    assert set(result.aggregate_a) == {"recall_at_k", "answer_relevancy", "faithfulness"}
    assert result.summary["a_wins"] + result.summary["b_wins"] + result.summary["ties"] == len(result.cases)
