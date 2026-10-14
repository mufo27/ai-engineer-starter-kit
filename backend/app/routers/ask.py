"""POST /v1/ask — grounded RAG question answering with citations + cost."""
from __future__ import annotations

import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.config import get_settings
from app.core.cost import UsageRecord
from app.core.deps_auth import PrincipalDep, request_id
from app.core.errors import RateLimitError
from app.core.metrics import METRICS
from app.deps import SERVICES

router = APIRouter(prefix="/v1", tags=["ask"])
_settings = get_settings()


class AskIn(BaseModel):
    question: str = Field(min_length=1)
    k: int = 4
    prompt_name: str = "rag_default"
    prompt_version: int | None = None
    tenant_budget: int | None = None


class CitationOut(BaseModel):
    marker: int
    chunk_id: str
    document_id: str
    snippet: str
    score: float


class AskOut(BaseModel):
    request_id: str
    answer: str
    citations: list[CitationOut]
    retrieved: int
    prompt_name: str
    prompt_version: int
    provider: str
    model: str
    task_type: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: int


@router.post("/ask", response_model=AskOut)
async def ask(body: AskIn, request: Request, principal: PrincipalDep) -> AskOut:
    services = getattr(request.app.state, "services", SERVICES)
    principal.require("ask")

    decision = await services.rate_limiter.acquire(principal.tenant_id)
    if not decision.allowed:
        raise RateLimitError("Too many requests", detail={"retry_after": decision.retry_after})
    await services.quota.check_and_increment(principal.tenant_id)
    budget = body.tenant_budget or _settings.default_token_budget
    await services.usage.assert_budget(principal.tenant_id, budget)

    rid = request_id()
    trace = services.tracer.start("ask", user_id=principal.tenant_id, metadata={"request_id": rid})
    with trace.span("retrieve+generate"):
        result = await services.rag.ask(
            tenant_id=principal.tenant_id, question=body.question, k=body.k,
            prompt_name=body.prompt_name, prompt_version=body.prompt_version,
        )
    trace.generation(
        name="ask", model=result.model, provider=result.provider,
        prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
        cost_usd=result.cost_usd, prompt_version=result.prompt_version, retrieved=result.retrieved,
    )
    trace.end()

    await services.usage.record(
        UsageRecord(
            tenant_id=principal.tenant_id, request_id=rid, model=result.model, provider=result.provider,
            task_type=result.task_type, prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens, cost_usd=result.cost_usd, latency_ms=result.latency_ms,
        )
    )
    METRICS.observe_llm(
        principal.tenant_id, result.provider, result.prompt_tokens, result.completion_tokens, result.cost_usd
    )

    return AskOut(
        request_id=rid, answer=result.answer,
        citations=[CitationOut(**c.__dict__) for c in result.citations],
        retrieved=result.retrieved, prompt_name=result.prompt_name, prompt_version=result.prompt_version,
        provider=result.provider, model=result.model, task_type=result.task_type,
        prompt_tokens=result.prompt_tokens, completion_tokens=result.completion_tokens,
        total_tokens=result.prompt_tokens + result.completion_tokens,
        cost_usd=result.cost_usd, latency_ms=result.latency_ms,
    )


@router.post("/ask/stream")
async def ask_stream(body: AskIn, request: Request, principal: PrincipalDep) -> StreamingResponse:
    """Server-Sent Events: streams citations, then answer deltas, then a final summary."""
    services = getattr(request.app.state, "services", SERVICES)
    principal.require("ask")

    decision = await services.rate_limiter.acquire(principal.tenant_id)
    if not decision.allowed:
        raise RateLimitError("Too many requests", detail={"retry_after": decision.retry_after})
    await services.quota.check_and_increment(principal.tenant_id)
    budget = body.tenant_budget or _settings.default_token_budget
    await services.usage.assert_budget(principal.tenant_id, budget)

    rid = request_id()

    async def gen():
        async for ev in services.rag.ask_stream(
            tenant_id=principal.tenant_id, question=body.question, k=body.k,
            prompt_name=body.prompt_name, prompt_version=body.prompt_version,
        ):
            if ev["type"] == "citations":
                payload = {k: v for k, v in ev.items()}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            elif ev["type"] == "delta":
                payload = {"type": "delta", "text": ev["text"]}
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            else:  # final
                r = ev["result"]
                await services.usage.record(
                    UsageRecord(
                        tenant_id=principal.tenant_id, request_id=rid, model=r.model, provider=r.provider,
                        task_type=r.task_type, prompt_tokens=r.prompt_tokens,
                        completion_tokens=r.completion_tokens, cost_usd=r.cost_usd, latency_ms=r.latency_ms,
                    )
                )
                summary = {
                    "type": "final", "request_id": rid, "answer": r.answer,
                    "provider": r.provider, "model": r.model, "task_type": r.task_type,
                    "prompt_name": r.prompt_name, "prompt_version": r.prompt_version,
                    "prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens,
                    "total_tokens": r.prompt_tokens + r.completion_tokens,
                    "cost_usd": r.cost_usd, "latency_ms": r.latency_ms,
                }
                yield f"data: {json.dumps(summary, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")
