"""Rate limiting: token bucket QPS + monthly quota fail-closed."""
from __future__ import annotations

import pytest

from app.core.errors import RateLimitError
from app.core.rate_limit import InMemoryRateLimiter, MonthlyQuota, TokenBucket


def test_token_bucket_burst_then_reject():
    b = TokenBucket(capacity=2, refill_rate=0)  # no refill
    assert b.take().allowed
    assert b.take().allowed
    d = b.take()
    assert not d.allowed
    assert d.retry_after > 0


@pytest.mark.asyncio
async def test_limiter_per_tenant_isolation(limiter: InMemoryRateLimiter):
    for _ in range(3):
        assert (await limiter.acquire("a")).allowed
    assert not (await limiter.acquire("a")).allowed
    # different tenant unaffected
    assert (await limiter.acquire("b")).allowed


@pytest.mark.asyncio
async def test_monthly_quota_fail_closed(quota: MonthlyQuota):
    for _ in range(5):
        await quota.check_and_increment("t1")  # limit=5
    with pytest.raises(RateLimitError):
        await quota.check_and_increment("t1")
