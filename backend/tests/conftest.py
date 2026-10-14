"""Shared test fixtures. Tests run without Docker/DB/Redis."""
from __future__ import annotations

import pytest

from app.core.auth import Principal
from app.core.cost import InMemoryUsageStore, UsageTracker
from app.core.rate_limit import InMemoryRateLimiter, MonthlyQuota
from app.services.llm_router import LLMRouter


@pytest.fixture
def principal() -> Principal:
    return Principal(
        tenant_id="t-demo",
        tenant_name="demo",
        scopes={"chat", "ask", "documents", "usage"},
    )


@pytest.fixture
def router_mock() -> LLMRouter:
    # No real clients -> mock provider path
    return LLMRouter(openai_client=None, anthropic_client=None, strict=False)


@pytest.fixture
def tracker() -> UsageTracker:
    return UsageTracker(InMemoryUsageStore())


@pytest.fixture
def limiter() -> InMemoryRateLimiter:
    return InMemoryRateLimiter(qps=3)


@pytest.fixture
def quota() -> MonthlyQuota:
    return MonthlyQuota(redis_client=None, limit=5)
