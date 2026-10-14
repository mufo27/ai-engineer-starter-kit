"""POST /v1/chat — the flagship endpoint exercising the whole pipeline.

Pipeline order (each stage can fail-closed):
  auth -> scope check -> rate limit (QPS) -> monthly quota -> budget check
  -> LLM router (retry + circuit breaker) -> record usage -> response
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.config import get_settings
from app.core.cost import UsageRecord
from app.core.deps_auth import PrincipalDep, request_id
from app.core.errors import RateLimitError
from app.deps import SERVICES
from app.services.llm_router import ChatMessage, TaskType

router = APIRouter(prefix="/v1", tags=["chat"])
_settings = get_settings()


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    task: TaskType | None = None          # force a task type (else auto-classified)
    model: str | None = None              # pin a specific model (else routed)
    tenant_budget: int | None = None      # override default monthly token budget


class ChatOut(BaseModel):
    request_id: str
    reply: str
    provider: str
    model: str
    task_type: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    latency_ms: int


@router.post("/chat", response_model=ChatOut)
async def chat(body: ChatIn, request: Request, principal: PrincipalDep) -> ChatOut:
    services = getattr(request.app.state, "services", SERVICES)
    principal.require("chat")

    # 1) QPS token bucket
    decision = await services.rate_limiter.acquire(principal.tenant_id)
    if not decision.allowed:
        raise RateLimitError("Too many requests", detail={"retry_after": decision.retry_after})

    # 2) monthly request quota (fail-closed inside)
    await services.quota.check_and_increment(principal.tenant_id)

    # 3) token budget guard (fail-closed)
    budget = body.tenant_budget or _settings.default_token_budget
    await services.usage.assert_budget(principal.tenant_id, budget)

    # 4) route + call (retry/circuit-breaker live in the router)
    result = await services.router.chat(body.messages, task=body.task, preferred_model=body.model)
    rid = request_id()

    # 5) record usage for cost accounting
    await services.usage.record(
        UsageRecord(
            tenant_id=principal.tenant_id,
            request_id=rid,
            model=result.model,
            provider=result.provider,
            task_type=result.task_type,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            cost_usd=result.cost_usd,
            latency_ms=result.latency_ms,
        )
    )

    return ChatOut(
        request_id=rid,
        reply=result.text,
        provider=result.provider,
        model=result.model,
        task_type=result.task_type,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        total_tokens=result.prompt_tokens + result.completion_tokens,
        cost_usd=round(result.cost_usd, 8),
        latency_ms=result.latency_ms,
    )
