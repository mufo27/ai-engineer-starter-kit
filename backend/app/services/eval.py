"""RAG eval: deterministic metrics + golden-set runner + A/B prompt comparison.

Lives in the backend so BOTH the CLI (eval/run.py) and the /v1/eval/compare
endpoint (used by the dashboard) share one implementation.

Metrics (lexical, no LLM-judge -> reproducible in CI):
  - recall_at_k:      expected source terms present in retrieved context (retrieval quality)
  - answer_relevancy: token overlap between answer and expected answer
  - faithfulness:     fraction of answer tokens grounded in retrieved context
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.services.embeddings import MockEmbedder
from app.services.llm_router import LLMRouter
from app.services.prompt_store import InMemoryPromptStore
from app.services.providers import MockProvider, ProviderRegistry
from app.services.rag import RAGService
from app.services.vectorstore import InMemoryVectorStore

_TOKEN = re.compile(r"[a-zA-Z0-9\u0E00-\u0E7F]+")
GOLDEN_PATH = Path(__file__).resolve().parents[1] / "data" / "golden.json"


def tokens(text: str) -> set[str]:
    return set(_TOKEN.findall(text.lower()))


def recall_at_k(expected_terms: list[str], retrieved_text: str) -> float:
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


def score_case(expected_terms: list[str], expected_answer: str, answer: str, retrieved_text: str) -> dict[str, float]:
    return {
        "recall_at_k": round(recall_at_k(expected_terms, retrieved_text), 4),
        "answer_relevancy": round(answer_relevancy(answer, expected_answer), 4),
        "faithfulness": round(faithfulness(answer, retrieved_text), 4),
    }


def load_golden() -> list[dict]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["cases"]


def _mock_router() -> LLMRouter:
    return LLMRouter(ProviderRegistry([MockProvider()]), strict=False)


async def run_case(rag: RAGService, case: dict, *, prompt_name: str = "rag_default",
                   prompt_version: int | None = None) -> dict:
    for doc in case["documents"]:
        await rag.ingest(tenant_id="eval", title=doc["title"], text=doc["text"])
    result = await rag.ask(tenant_id="eval", question=case["question"], k=4,
                           prompt_name=prompt_name, prompt_version=prompt_version)
    retrieved_text = "\n".join(c.snippet for c in result.citations)
    metrics = score_case(case["expected_terms"], case["expected_answer"], result.answer, retrieved_text)
    return {
        "id": case["id"], "question": case["question"], "answer": result.answer[:120],
        "retrieved": result.retrieved, **metrics,
    }


async def run_suite(cases: list[dict] | None = None, *, router: LLMRouter | None = None) -> list[dict]:
    cases = cases or load_golden()
    router = router or _mock_router()
    rows = []
    for case in cases:
        rag = RAGService(embedder=MockEmbedder(), store=InMemoryVectorStore(),
                         prompts=InMemoryPromptStore(), router=router)
        rows.append(await run_case(rag, case))
    return rows


def aggregate(rows: list[dict]) -> dict[str, float]:
    n = max(len(rows), 1)
    return {
        "recall_at_k": round(sum(r["recall_at_k"] for r in rows) / n, 4),
        "answer_relevancy": round(sum(r["answer_relevancy"] for r in rows) / n, 4),
        "faithfulness": round(sum(r["faithfulness"] for r in rows) / n, 4),
    }


@dataclass
class ABResult:
    prompt_name: str
    version_a: int
    version_b: int
    cases: list[dict]
    aggregate_a: dict
    aggregate_b: dict
    summary: dict


async def compare_prompts(rag_prompts: InMemoryPromptStore, *, prompt_name: str,
                          version_a: int, version_b: int,
                          body_a: str | None = None, body_b: str | None = None,
                          cases: list[dict] | None = None,
                          router: LLMRouter | None = None) -> ABResult:
    """Run the golden set through two prompt versions (or inline bodies) and diff."""
    cases = cases or load_golden()
    router = router or _mock_router()

    # Resolve/create versions. Inline bodies get added as new versions.
    va = version_a
    if body_a is not None:
        tpl = await rag_prompts.add(name=prompt_name, body=body_a, created_by="ab-eval")
        va = tpl.version
    vb = version_b
    if body_b is not None:
        tpl = await rag_prompts.add(name=prompt_name, body=body_b, created_by="ab-eval")
        vb = tpl.version

    rows_a, rows_b, cases_out = [], [], []
    summary = {"a_wins": 0, "b_wins": 0, "ties": 0}
    for case in cases:
        rag_a = RAGService(embedder=MockEmbedder(), store=InMemoryVectorStore(), prompts=rag_prompts, router=router)
        rag_b = RAGService(embedder=MockEmbedder(), store=InMemoryVectorStore(), prompts=rag_prompts, router=router)
        ra = await run_case(rag_a, case, prompt_name=prompt_name, prompt_version=va)
        rb = await run_case(rag_b, case, prompt_name=prompt_name, prompt_version=vb)
        rows_a.append(ra)
        rows_b.append(rb)
        # winner by combined recall + faithfulness (mock answers tie on relevancy)
        sa = ra["recall_at_k"] + ra["faithfulness"]
        sb = rb["recall_at_k"] + rb["faithfulness"]
        winner = "a" if sa > sb else "b" if sb > sa else "tie"
        summary["ties" if winner == "tie" else f"{winner}_wins"] += 1
        cases_out.append({"id": ra["id"], "question": ra["question"], "a": ra, "b": rb, "winner": winner})

    agg_a, agg_b = aggregate(rows_a), aggregate(rows_b)
    return ABResult(prompt_name, va, vb, cases_out, agg_a, agg_b, summary)
