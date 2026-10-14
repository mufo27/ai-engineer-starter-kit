#!/usr/bin/env python3
"""RAG eval CLI — thin wrapper over app.services.eval.

Runs the golden set through the RAG pipeline, writes a CSV report, and gates on
mean recall@k (exit 1 below threshold) for CI. Mock LLM by default (offline);
--live uses real providers from .env.

Usage:
    python eval/run.py [--min-score 0.8] [--live] [--out eval/reports/report.csv]
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.eval import aggregate, load_golden, run_suite  # noqa: E402


def _router(live: bool):
    if not live:
        return None  # run_suite defaults to mock router
    from app.deps import _build_registry
    from app.services.llm_router import LLMRouter

    return LLMRouter(_build_registry(), strict=False)


async def run(min_score: float, live: bool, report_path: Path) -> int:
    rows = await run_suite(load_golden(), router=_router(live))
    means = aggregate(rows)

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
    ap.add_argument("--min-score", type=float, default=0.8)
    ap.add_argument("--live", action="store_true")
    ap.add_argument("--out", default="eval/reports/report.csv")
    args = ap.parse_args()
    return asyncio.run(run(args.min_score, args.live, ROOT / args.out))


if __name__ == "__main__":
    raise SystemExit(main())
