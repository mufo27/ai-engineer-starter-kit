"""LLM Router — the core of the kit.

Responsibilities:
  1. Classify a request into a task type (simple / complex / reasoning / cheap).
  2. Route to the cheapest capable provider/model that is currently healthy.
  3. Wrap every call with retry + circuit breaker.
  4. Count tokens + compute cost (fail-closed: no provider -> 503 in strict mode).

Providers implement a tiny `complete()` interface so the router is provider-agnostic
and trivially testable (a MockProvider is always available).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

from app.core.circuit_breaker import BreakerRegistry
from app.core.errors import CircuitOpenError, NoProviderAvailableError


class TaskType(StrEnum):
    CLASSIFY = "classify"   # cheap, short output
    SIMPLE = "simple"       # general chat
    REASONING = "reasoning" # long / complex -> smart model
    EXTRACT = "extract"     # structured output


# Static price table (USD per 1M tokens). Update as provider pricing changes.
@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    input_price_per_m: float
    output_price_per_m: float
    max_output_tokens: int = 1024
    tier: int = 1  # 1=cheap, 2=balanced, 3=smart


MOCK = ModelSpec("mock", "mock", 0.0, 0.0, 1024, tier=1)

CATALOG: dict[str, ModelSpec] = {
    "gpt-4o-mini": ModelSpec("openai", "gpt-4o-mini", 0.15, 0.60, 1024, tier=1),
    "gpt-4o": ModelSpec("openai", "gpt-4o", 2.50, 10.00, 2048, tier=3),
    "claude-3-5-haiku": ModelSpec("anthropic", "claude-3-5-haiku-20241022", 0.80, 4.00, 1024, tier=2),
    "claude-3-5-sonnet": ModelSpec("anthropic", "claude-3-5-sonnet-20241022", 3.00, 15.00, 2048, tier=3),
    "mock": MOCK,
}

# Which models are eligible per task, ordered cheapest-first.
ROUTING_TABLE: dict[TaskType, list[str]] = {
    TaskType.CLASSIFY: ["gpt-4o-mini", "claude-3-5-haiku"],
    TaskType.EXTRACT: ["gpt-4o-mini", "claude-3-5-haiku"],
    TaskType.SIMPLE: ["gpt-4o-mini", "claude-3-5-haiku", "gpt-4o"],
    TaskType.REASONING: ["claude-3-5-sonnet", "gpt-4o"],
}

_KEYWORDS_REASONING = ("analyze", "prove", "architect", "design", "reason", "multi-step", "tradeoff")
_KEYWORDS_CLASSIFY = ("classify", "label", "categorize", "sentiment")
_KEYWORDS_EXTRACT = ("extract", "parse", "structured", "json")


def classify_task(prompt: str, *, force: TaskType | None = None) -> TaskType:
    """Heuristic task classifier. Deterministic + zero-cost.

    A production kit would optionally route this through a tiny model; the
    heuristic keeps the default path cheap and testable.
    """
    if force:
        return force
    p = prompt.lower()
    if any(k in p for k in _KEYWORDS_CLASSIFY):
        return TaskType.CLASSIFY
    if any(k in p for k in _KEYWORDS_EXTRACT):
        return TaskType.EXTRACT
    if any(k in p for k in _KEYWORDS_REASONING) or len(p) > 800:
        return TaskType.REASONING
    return TaskType.SIMPLE


@dataclass
class ChatMessage:
    role: str
    content: str


@dataclass
class LLMResult:
    text: str
    spec: ModelSpec
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    provider: str
    model: str
    cost_usd: float = 0.0
    raw: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.cost_usd = compute_cost(self.spec, self.prompt_tokens, self.completion_tokens)


def compute_cost(spec: ModelSpec, prompt_tokens: int, completion_tokens: int) -> float:
    return (
        prompt_tokens / 1_000_000 * spec.input_price_per_m
        + completion_tokens / 1_000_000 * spec.output_price_per_m
    )


def estimate_tokens(text: str) -> int:
    """Cheap token estimate when tiktoken is unavailable (chars/4)."""
    return max(1, len(text) // 4)


class LLMRouter:
    def __init__(
        self,
        *,
        openai_client=None,
        anthropic_client=None,
        strict: bool = False,
        breakers: BreakerRegistry | None = None,
    ) -> None:
        self.openai = openai_client
        self.anthropic = anthropic_client
        self.strict = strict
        self.breakers = breakers or BreakerRegistry()

    # ── provider availability ──────────────────────────
    def _provider_available(self, provider: str) -> bool:
        if provider == "openai":
            return self.openai is not None
        if provider == "anthropic":
            return self.anthropic is not None
        return True  # mock always available

    def _candidates(self, task: TaskType) -> list[ModelSpec]:
        out: list[ModelSpec] = []
        for name in ROUTING_TABLE[task]:
            spec = CATALOG[name]
            if self._provider_available(spec.provider) and self.breakers.get(spec.provider).allow():
                out.append(spec)
        return out

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        task: TaskType | None = None,
        preferred_model: str | None = None,
    ) -> LLMResult:
        prompt = messages[-1].content if messages else ""
        task_type = classify_task(prompt, force=task)

        if preferred_model and preferred_model in CATALOG:
            candidates = [CATALOG[preferred_model]]
        else:
            candidates = self._candidates(task_type)

        if not candidates:
            if self.strict:
                raise NoProviderAvailableError(
                    "No healthy provider available (strict mode)",
                    detail={"task": task_type.value, "breakers": self.breakers.snapshot_all()},
                )
            candidates = [MOCK]  # dev fallback

        last_err: Exception | None = None
        for spec in candidates:
            breaker = self.breakers.get(spec.provider)
            if not breaker.allow():
                continue
            try:
                t0 = time.perf_counter()
                text, ptok, ctok = await self._call(spec, messages)
                latency = int((time.perf_counter() - t0) * 1000)
                breaker.record_success()
                return LLMResult(
                    text=text,
                    spec=spec,
                    prompt_tokens=ptok,
                    completion_tokens=ctok,
                    latency_ms=latency,
                    provider=spec.provider,
                    model=spec.model,
                )
            except CircuitOpenError:
                continue
            except Exception as exc:  # provider call failed
                breaker.record_failure()
                last_err = exc
                continue

        if self.strict:
            raise NoProviderAvailableError(
                "All candidate providers failed",
                detail={"task": task_type.value, "last_error": str(last_err)},
            )
        # last resort mock so dev never hard-fails outside strict mode
        text, ptok, ctok = await self._call(MOCK, messages)
        return LLMResult(
            text=text, spec=MOCK, prompt_tokens=ptok, completion_tokens=ctok,
            latency_ms=0, provider="mock", model="mock",
        )

    async def _call(self, spec: ModelSpec, messages: list[ChatMessage]) -> tuple[str, int, int]:
        if spec.provider == "mock":
            return await self._call_mock(spec, messages)
        if spec.provider == "openai":
            return await self._call_openai(spec, messages)
        if spec.provider == "anthropic":
            return await self._call_anthropic(spec, messages)
        raise NoProviderAvailableError(f"Unknown provider {spec.provider}")

    async def _call_mock(self, spec: ModelSpec, messages: list[ChatMessage]) -> tuple[str, int, int]:
        prompt = messages[-1].content if messages else ""
        reply = f"[mock:{spec.model}] echo({len(prompt)} chars)"
        return reply, estimate_tokens(prompt), estimate_tokens(reply)

    async def _call_openai(self, spec: ModelSpec, messages: list[ChatMessage]) -> tuple[str, int, int]:
        resp = await self.openai.chat.completions.create(
            model=spec.model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            max_tokens=spec.max_output_tokens,
        )
        usage = resp.usage
        return resp.choices[0].message.content or "", usage.prompt_tokens, usage.completion_tokens

    async def _call_anthropic(self, spec: ModelSpec, messages: list[ChatMessage]) -> tuple[str, int, int]:
        system = next((m.content for m in messages if m.role == "system"), None)
        convo = [m for m in messages if m.role != "system"]
        resp = await self.anthropic.messages.create(
            model=spec.model,
            max_tokens=spec.max_output_tokens,
            system=system,
            messages=[{"role": m.role, "content": m.content} for m in convo],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return text, resp.usage.input_tokens, resp.usage.output_tokens
