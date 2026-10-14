"""LLM Router — provider-agnostic orchestration on top of the ProviderRegistry.

Responsibilities:
  1. Classify a request into a task type (classify/simple/reasoning/extract).
  2. Rank catalog models by how well their tier fits the task + price.
  3. Filter to models whose provider is registered, available, and breaker-open.
  4. Call the provider (retry/circuit-breaker), count cost, return a result.

Adding a vendor no longer touches this file — register a provider in deps.py.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

from app.core.circuit_breaker import BreakerRegistry
from app.core.errors import NoProviderAvailableError
from app.services.providers.base import (
    ChatMessage,
    ModelSpec,
    compute_cost,
    estimate_tokens,
)
from app.services.providers.registry import ProviderRegistry

# Re-exported for backward-compatible imports elsewhere.
__all__ = [
    "CATALOG", "ChatMessage", "LLMResult", "LLMRouter", "ModelSpec",
    "TaskType", "classify_task", "compute_cost", "estimate_tokens",
]


class TaskType(StrEnum):
    CLASSIFY = "classify"   # cheap, short output
    SIMPLE = "simple"       # general chat
    REASONING = "reasoning" # long / complex -> smart model
    EXTRACT = "extract"     # structured output


# ── Model catalog (provider, model, in $/M, out $/M, max_out, tier) ──────────
# Prices are representative; keep current with provider pricing pages.
MOCK = ModelSpec("mock", "mock", 0.0, 0.0, 1024, tier=1)

CATALOG: dict[str, ModelSpec] = {
    # OpenAI
    "gpt-4o-mini": ModelSpec("openai", "gpt-4o-mini", 0.15, 0.60, 1024, tier=1),
    "gpt-4o": ModelSpec("openai", "gpt-4o", 2.50, 10.00, 2048, tier=3),
    # Anthropic
    "claude-3-5-haiku": ModelSpec("anthropic", "claude-3-5-haiku-20241022", 0.80, 4.00, 1024, tier=2),
    "claude-3-5-sonnet": ModelSpec("anthropic", "claude-3-5-sonnet-20241022", 3.00, 15.00, 2048, tier=3),
    # Google Gemini (native)
    "gemini-3.5-flash-lite": ModelSpec("gemini", "gemini-3.5-flash-lite", 0.10, 0.40, 1024, tier=1),
    "gemini-3.8-flash": ModelSpec("gemini", "gemini-3.8-flash", 0.30, 2.50, 1024, tier=2),
    "gemini-3.1-pro-preview": ModelSpec("gemini", "gemini-3.1-pro-preview", 1.25, 10.00, 2048, tier=3),
    # OpenAI-compatible extras (only routable if the provider is registered in deps)
    "llama-3.3-70b-versatile": ModelSpec("groq", "llama-3.3-70b-versatile", 0.59, 0.79, 1024, tier=2),
    "deepseek-chat": ModelSpec("deepseek", "deepseek-chat", 0.27, 1.10, 1024, tier=1),
    "mock": MOCK,
}

# Target tier per task type.
TASK_TIER: dict[TaskType, int] = {
    TaskType.CLASSIFY: 1,
    TaskType.EXTRACT: 1,
    TaskType.SIMPLE: 2,
    TaskType.REASONING: 3,
}

_KEYWORDS_REASONING = ("analyze", "prove", "architect", "design", "reason", "multi-step", "tradeoff")
_KEYWORDS_CLASSIFY = ("classify", "label", "categorize", "sentiment")
_KEYWORDS_EXTRACT = ("extract", "parse", "structured", "json")


def classify_task(prompt: str, *, force: TaskType | None = None) -> TaskType:
    """Deterministic, zero-cost heuristic task classifier."""
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
class LLMResult:
    text: str
    spec: ModelSpec
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    provider: str
    model: str
    task_type: str = "simple"
    cost_usd: float = 0.0
    raw: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.cost_usd = compute_cost(self.spec, self.prompt_tokens, self.completion_tokens)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMRouter:
    def __init__(
        self,
        registry: ProviderRegistry,
        *,
        strict: bool = False,
        breakers: BreakerRegistry | None = None,
        catalog: dict[str, ModelSpec] | None = None,
    ) -> None:
        self.registry = registry
        self.strict = strict
        self.breakers = breakers or BreakerRegistry()
        self.catalog = catalog or CATALOG

    def _eligible(self, spec: ModelSpec) -> bool:
        if spec.provider == "mock":
            return False  # mock only via explicit fallback/preference
        if not self.registry.is_available(spec.provider):
            return False
        return self.breakers.get(spec.provider).allow()

    def _candidates(self, task: TaskType) -> list[ModelSpec]:
        target = TASK_TIER[task]
        pool = [s for s in self.catalog.values() if self._eligible(s)]
        # rank: closest tier to target, then cheapest total price
        pool.sort(key=lambda s: (abs(s.tier - target), s.input_price_per_m + s.output_price_per_m))
        return pool

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        task: TaskType | None = None,
        preferred_model: str | None = None,
    ) -> LLMResult:
        prompt = messages[-1].content if messages else ""
        task_type = classify_task(prompt, force=task)

        if preferred_model and preferred_model in self.catalog:
            candidates = [self.catalog[preferred_model]]
        else:
            candidates = self._candidates(task_type)

        if not candidates:
            if self.strict:
                raise NoProviderAvailableError(
                    "No healthy provider available (strict mode)",
                    detail={"task": task_type.value, "breakers": self.breakers.snapshot_all()},
                )
            candidates = [MOCK]

        last_err: Exception | None = None
        for spec in candidates:
            provider = self.registry.get(spec.provider)
            breaker = self.breakers.get(spec.provider)
            if provider is None or not breaker.allow():
                continue
            try:
                t0 = time.perf_counter()
                res = await provider.complete(
                    messages, model=spec.model, max_output_tokens=spec.max_output_tokens
                )
                latency = int((time.perf_counter() - t0) * 1000)
                breaker.record_success()
                return LLMResult(
                    text=res.text, spec=spec, prompt_tokens=res.prompt_tokens,
                    completion_tokens=res.completion_tokens, latency_ms=latency,
                    provider=spec.provider, model=spec.model, task_type=task_type.value, raw=res.raw,
                )
            except Exception as exc:  # provider call failed -> try next candidate
                breaker.record_failure()
                last_err = exc
                continue

        if self.strict:
            raise NoProviderAvailableError(
                "All candidate providers failed",
                detail={"task": task_type.value, "last_error": str(last_err)},
            )
        # non-strict last resort: mock so dev never hard-fails
        mock = self.registry.get("mock")
        if mock is None:
            raise NoProviderAvailableError("No provider and no mock registered")
        t0 = time.perf_counter()
        res = await mock.complete(messages, model="mock")
        return LLMResult(
            text=res.text, spec=MOCK, prompt_tokens=res.prompt_tokens,
            completion_tokens=res.completion_tokens, latency_ms=int((time.perf_counter() - t0) * 1000),
            provider="mock", model="mock", task_type=task_type.value,
        )

    async def stream_chat(
        self,
        messages: list[ChatMessage],
        *,
        task: TaskType | None = None,
        preferred_model: str | None = None,
    ):
        """Async generator yielding {'type':'delta','text':...} then {'type':'final','result':LLMResult}."""
        prompt = messages[-1].content if messages else ""
        task_type = classify_task(prompt, force=task)

        if preferred_model and preferred_model in self.catalog:
            candidates = [self.catalog[preferred_model]]
        else:
            candidates = self._candidates(task_type)
        if not candidates:
            if self.strict:
                raise NoProviderAvailableError("No healthy provider (strict mode)",
                                               detail={"task": task_type.value})
            candidates = [MOCK]

        last_err: Exception | None = None
        for spec in candidates:
            provider = self.registry.get(spec.provider)
            breaker = self.breakers.get(spec.provider)
            if provider is None or not breaker.allow():
                continue
            try:
                t0 = time.perf_counter()
                acc: list[str] = []
                if hasattr(provider, "astream"):
                    async for piece in provider.astream(
                        messages, model=spec.model, max_output_tokens=spec.max_output_tokens
                    ):
                        acc.append(piece)
                        yield {"type": "delta", "text": piece}
                else:
                    res = await provider.complete(
                        messages, model=spec.model, max_output_tokens=spec.max_output_tokens
                    )
                    acc.append(res.text)
                    yield {"type": "delta", "text": res.text}
                text = "".join(acc)
                breaker.record_success()
                result = LLMResult(
                    text=text, spec=spec, prompt_tokens=estimate_tokens(prompt),
                    completion_tokens=estimate_tokens(text), latency_ms=int((time.perf_counter() - t0) * 1000),
                    provider=spec.provider, model=spec.model, task_type=task_type.value,
                )
                yield {"type": "final", "result": result}
                return
            except Exception as exc:  # try next candidate
                breaker.record_failure()
                last_err = exc
                continue

        if self.strict:
            raise NoProviderAvailableError("All streaming providers failed",
                                           detail={"task": task_type.value, "last_error": str(last_err)})
        mock = self.registry.get("mock")
        if mock is None:
            raise NoProviderAvailableError("No provider and no mock registered")
        t0 = time.perf_counter()
        acc = []
        if hasattr(mock, "astream"):
            async for piece in mock.astream(messages, model="mock"):
                acc.append(piece)
                yield {"type": "delta", "text": piece}
        else:
            res = await mock.complete(messages, model="mock")
            acc.append(res.text)
            yield {"type": "delta", "text": res.text}
        text = "".join(acc)
        yield {"type": "final", "result": LLMResult(
            text=text, spec=MOCK, prompt_tokens=estimate_tokens(prompt), completion_tokens=estimate_tokens(text),
            latency_ms=int((time.perf_counter() - t0) * 1000), provider="mock", model="mock",
            task_type=task_type.value,
        )}
