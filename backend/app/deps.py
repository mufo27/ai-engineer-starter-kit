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
from app.services.llm_router import LLMRouter

_settings = get_settings()


@dataclass
class Services:
    router: LLMRouter
    api_keys: ApiKeyRepository
    rate_limiter: InMemoryRateLimiter | RedisRateLimiter
    quota: MonthlyQuota
    usage: UsageTracker


def _build_llm_clients():
    openai_client = None
    anthropic_client = None
    if _settings.openai_enabled:
        from openai import AsyncOpenAI

        openai_client = AsyncOpenAI(api_key=_settings.openai_api_key, base_url=_settings.openai_base_url)
    if _settings.anthropic_enabled:
        from anthropic import AsyncAnthropic

        anthropic_client = AsyncAnthropic(api_key=_settings.anthropic_api_key, base_url=_settings.anthropic_base_url)
    return openai_client, anthropic_client


def build_services(redis_client=None, *, use_sql: bool = False) -> Services:
    """redis_client: async redis handle or None. use_sql: SQL-backed stores."""
    openai_client, anthropic_client = _build_llm_clients()
    router = LLMRouter(
        openai_client=openai_client,
        anthropic_client=anthropic_client,
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

    return Services(
        router=router,
        api_keys=api_keys,
        rate_limiter=rate_limiter,
        quota=quota,
        usage=UsageTracker(usage_store),
    )


# Process-wide default (dev/test). Production overrides via app.state in lifespan.
SERVICES = build_services(redis_client=None, use_sql=False)
