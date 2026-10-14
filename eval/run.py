#!/usr/bin/env python3
"""RAG eval harness.

Runs every golden case through the RAG pipeline and scores retrieval + answer
quality, writes a CSV report, and (for CI) exits non-zero if the mean
retrieval recall is below --min-score.

Usage:
    python eval/run.py                       # mock LLM, gate on recall@k >= 0.8
    python eval/run.py --min-score 0.9       # stricter
    python eval/run.py --live                # use real providers from .env if keys set
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from pathlib import Path

# Make the backend + eval package importable when run from anywhere.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from app.services.embeddings import MockEmbedder  # noqa: E402
from app.services.llm_router import LLMRouter  # noqa: E402
from app.services.prompt_store import InMemoryPromptStore  # noqa: E402
from app.services.providers import MockProvider, ProviderRegistry  # noqa: E402
from app.services.rag import RAGService  # noqa: E402
from app.services.vectorstore import InMemoryVectorStore  # noqa: E402
from eval.scoring import score_case  # noqa: E402


def _build_router(live: bool):
    if not live:
        return LLMRouter(ProviderRegistry([MockProvider()]), strict=False)
    from app.config import get_settings
    from app.deps import _build_registry

    return LLMRouter(_build_registry(), strict=False)


async def run(min_score: float, live: bool, report_path: Path) -> int:
    cases = json.loads((ROOT / "eval" / "golden" / "qa.json").read_text(encoding="utf-8"))["cases"]
    router = _build_router(live)
    rows = []

    for case in cases:
        rag = RAGService(
            embedder=MockEmbedder(), store=InMemoryVectorStore(),
            prompts=InMemoryPromptStore(), router=router,
        )
        for doc in case["documents"]:
            await rag.ingest(tenant_id="eval", title=doc["title"], text=doc["text"])
        result = await rag.ask(tenant_id="eval", question=case["question"], k=4)
        retrieved_text = "\n".join(c.snippet for c in result.citations)
        metrics = score_case(case["question"], case["expected_terms"], case["expected_answer"], result.answer, retrieved_text)
        rows.append({
            "id": case["id"], "question": case["question"], "answer": result.answer[:80],
            "retrieved": result.retrieved, **metrics,
        })

    n = len(rows)
    means = {
        "recall_at_k": sum(r["recall_at_k"] for r in rows) / n,
        "answer_relevancy": sum(r["answer_relevancy"] for r in rows) / n,
        "faithfulness": sum(r["faithfulness"] for r in rows) / n,
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n{'id':<10}{'recall':>8}{'relev':>8}{'faith':>8}   question")
    for r in rows:
        print(f"{r['id']:<10}{r['recall_at_k']:>8.2f}{r['answer_relevancy']:>8.2f}{r['faithfulness']:>8.2f}   {r['question'][:48]}")
    print(f"\nMEAN   recall={means['recall_at_k']:.3f}  relevancy={means['answer_relevancy']:.3f}  faithfulness={means['faithfulness']:.3f}")
    print(f"report -> {os.path.relpath(report_path, ROOT)}")

    passed = means["recall_at_k"] >= min_score
    print(f"GATE   recall_at_k {means['recall_at_k']:.3f} {'>=' if passed else '<'} {min_score:.2f} -> {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="RAG eval harness")
    ap.add_argument("--min-score", type=float, default=0.8, help="minimum mean recall@k to pass")
    ap.add_argument("--live", action="store_true", help="use real providers from .env")
    ap.add_argument("--out", default="eval/reports/report.csv", help="CSV report path")
    args = ap.parse_args()
    return asyncio.run(run(args.min_score, args.live, ROOT / args.out))


if __name__ == "__main__":
    raise SystemExit(main())
