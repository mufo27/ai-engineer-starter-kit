"""Cost tracking + budget guardrail (fail-closed)."""
from __future__ import annotations

import pytest

from app.core.cost import InMemoryUsageStore, UsageRecord, UsageTracker
from app.core.errors import BudgetExhaustedError


def _rec(tokens: int, cost: float = 0.01) -> UsageRecord:
    return UsageRecord(
        tenant_id="t1", request_id="r", model="mock", provider="mock",
        task_type="simple", prompt_tokens=tokens // 2, completion_tokens=tokens - tokens // 2,
        cost_usd=cost, latency_ms=1,
    )


@pytest.mark.asyncio
async def test_record_and_summary(tracker: UsageTracker):
    await tracker.record(_rec(100, 0.02))
    await tracker.record(_rec(50, 0.03))
    s = await tracker.summary("t1")
    assert s["month_tokens"] == 150
    assert s["month_cost_usd"] == pytest.approx(0.05)


@pytest.mark.asyncio
async def test_budget_fail_closed(tracker: UsageTracker):
    await tracker.record(_rec(1000))
    with pytest.raises(BudgetExhaustedError):
        await tracker.assert_budget("t1", budget=1000)
    # under budget passes
    await tracker.assert_budget("t1", budget=2000)


@pytest.mark.asyncio
async def test_budget_isolated_per_tenant(tracker: UsageTracker):
    await tracker.record(_rec(1000))
    await tracker.assert_budget("other", budget=1000)  # different tenant ok


@pytest.mark.asyncio
async def test_store_isolation():
    a = InMemoryUsageStore()
    b = InMemoryUsageStore()
    await a.add(_rec(10))
    assert await b.month_tokens("t1") == 0
