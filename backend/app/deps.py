"""Dependency wiring.

Builds the app's service singletons. In development/tests (no Redis/DB), it
falls back to in-memory implementations so the whole request path is exercisable
without Docker. In production the SQL/Redis-backed stores are used.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings
from app.core.auth import (
    ALL_SCOPES,
    ApiKeyRepository,
    InMemoryApiKeyRepository,
    Principal,
    SqlApiKeyRepository,
)
from app.core.circuit_breaker import BreakerRegistry
from app.core.cost import InMemoryUsageStore, SqlUsageStore, UsageStore, UsageTracker
from app.core.rate_limit import (
    InMemoryRateLimiter,
    MonthlyQuota,
    RedisRateLimiter,
)
from app.core.tracing import Tracer, build_tracer
from app.services.embeddings import build_embedder
from app.services.llm_router import LLMRouter
from app.services.prompt_store import InMemoryPromptStore, PromptStore
from app.services.providers import (
    AnthropicProvider,
    GeminiProvider,
    MockProvider,
    OpenAICompatProvider,
    ProviderRegistry,
)
from app.services.rag import RAGService
from app.services.vectorstore import InMemoryVectorStore, PgVectorStore, VectorStore

_settings = get_settings()


@dataclass
class Services:
    router: LLMRouter
    api_keys: ApiKeyRepository
    rate_limiter: InMemoryRateLimiter | RedisRateLimiter
    quota: MonthlyQuota
    usage: UsageTracker
    embedder: object
    vectorstore: VectorStore
    prompts: PromptStore
    rag: RAGService
    tracer: Tracer


def _build_registry() -> ProviderRegistry:
    """Assemble providers from config. Add a vendor here -> it becomes routable."""
    providers = [MockProvider()]

    if _settings.openai_enabled:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=_settings.openai_api_key, base_url=_settings.openai_base_url)
        providers.append(OpenAICompatProvider("openai", client))
    if _settings.anthropic_enabled:
        from anthropic import AsyncAnthropic

        aclient = AsyncAnthropic(api_key=_settings.anthropic_api_key, base_url=_settings.anthropic_base_url)
        providers.append(AnthropicProvider(aclient))
    if _settings.gemini_enabled:
        providers.append(GeminiProvider(_settings.gemini_api_key, base_url=_settings.gemini_base_url))

    # OpenAI-compatible extras: same schema, different base_url/key.
    for name, enabled, key, base_url in (
        ("groq", _settings.groq_enabled, _settings.groq_api_key, _settings.groq_base_url),
        ("openrouter", _settings.openrouter_enabled, _settings.openrouter_api_key, _settings.openrouter_base_url),
        ("deepseek", _settings.deepseek_enabled, _settings.deepseek_api_key, _settings.deepseek_base_url),
    ):
        if enabled:
            from openai import AsyncOpenAI

            providers.append(OpenAICompatProvider(name, AsyncOpenAI(api_key=key, base_url=base_url)))

    if _settings.ollama_enabled:
        from openai import AsyncOpenAI

        # Ollama needs no real key; a placeholder satisfies the client.
        oclient = AsyncOpenAI(api_key="ollama", base_url=_settings.ollama_base_url)
        providers.append(OpenAICompatProvider("ollama", oclient))

    return ProviderRegistry(providers)


def build_services(redis_client=None, *, use_sql: bool = False) -> Services:
    """redis_client: async redis handle or None. use_sql: SQL-backed stores."""
    registry = _build_registry()
    router = LLMRouter(
        registry,
        strict=_settings.strict_provider_mode,
        breakers=BreakerRegistry(),
    )

    api_keys: ApiKeyRepository
    usage_store: UsageStore
    rate_limiter: InMemoryRateLimiter | RedisRateLimiter
    quota: MonthlyQuota

    if use_sql:
        api_keys = SqlApiKeyRepository()
        usage_store = SqlUsageStore()
    else:
        mem = InMemoryApiKeyRepository()
        # Seed a demo tenant + key so the dev path is immediately usable.
        mem.register(
            "dev-key-123",
            Principal(tenant_id="00000000-0000-0000-0000-000000000001", tenant_name="demo", scopes=set(ALL_SCOPES)),
        )
        api_keys = mem
        usage_store = InMemoryUsageStore()

    if redis_client is not None:
        rate_limiter = RedisRateLimiter(redis_client, _settings.rate_limit_qps)
        quota = MonthlyQuota(redis_client, _settings.rate_limit_monthly_requests)
    else:
        rate_limiter = InMemoryRateLimiter(_settings.rate_limit_qps)
        quota = MonthlyQuota(None, _settings.rate_limit_monthly_requests)

    embedder = build_embedder(_settings)
    vectorstore: VectorStore = PgVectorStore() if use_sql else InMemoryVectorStore()
    prompts: PromptStore = InMemoryPromptStore()  # self-seeds the default RAG prompt
    rag = RAGService(embedder=embedder, store=vectorstore, prompts=prompts, router=router)
    tracer = build_tracer(_settings)

    return Services(
        router=router,
        api_keys=api_keys,
        rate_limiter=rate_limiter,
        quota=quota,
        usage=UsageTracker(usage_store),
        embedder=embedder,
        vectorstore=vectorstore,
        prompts=prompts,
        rag=rag,
        tracer=tracer,
    )


# Process-wide default (dev/test). Production overrides via app.state in lifespan.
SERVICES = build_services(redis_client=None, use_sql=False)
