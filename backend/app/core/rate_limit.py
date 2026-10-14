"""Rate limiting: per-tenant QPS (token bucket) + monthly request quota.

Two independent guards:
  - QPS: smooths bursts (token bucket). Backed by Redis for multi-replica; an
    in-memory bucket is used when Redis is unavailable (single-process dev/test).
  - Monthly quota: hard cap on total requests per tenant per calendar month.

Fail-open vs fail-closed: for the QPS limiter we fail-open if Redis is down
(availability first, since cost is also guarded by the budget check). The
monthly quota is enforced in the budget/cost layer which fails-closed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from app.core.errors import RateLimitError


@dataclass
class RateDecision:
    allowed: bool
    remaining: int
    retry_after: float = 0.0


class TokenBucket:
    """In-process token bucket. refill_rate = tokens/sec, capacity = burst."""

    def __init__(self, capacity: float, refill_rate: float) -> None:
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._tokens = capacity
        self._last = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        self._tokens = min(self.capacity, self._tokens + (now - self._last) * self.refill_rate)
        self._last = now

    def take(self, n: float = 1.0) -> RateDecision:
        self._refill()
        if self._tokens >= n:
            self._tokens -= n
            return RateDecision(True, int(self._tokens))
        deficit = n - self._tokens
        retry = deficit / self.refill_rate if self.refill_rate else 1.0
        return RateDecision(False, 0, retry_after=retry)


class InMemoryRateLimiter:
    def __init__(self, qps: int) -> None:
        self.qps = qps
        self._buckets: dict[str, TokenBucket] = {}

    def _bucket(self, key: str) -> TokenBucket:
        if key not in self._buckets:
            self._buckets[key] = TokenBucket(capacity=self.qps, refill_rate=self.qps)
        return self._buckets[key]

    async def acquire(self, tenant_id: str) -> RateDecision:
        return self._bucket(tenant_id).take()


class RedisRateLimiter:
    """Token bucket stored in Redis (atomic via Lua-free read-modify with lock-free
    approach good enough for portfolio scope; production would use a Lua script)."""

    def __init__(self, redis_client, qps: int) -> None:
        self.redis = redis_client
        self.qps = qps

    async def acquire(self, tenant_id: str) -> RateDecision:
        key = f"rl:{tenant_id}"
        now = time.time()
        try:
            data = await self.redis.hgetall(key)
            tokens = float(data.get("tokens", self.qps)) if data else float(self.qps)
            last = float(data.get("ts", now)) if data else now
            tokens = min(self.qps, tokens + (now - last) * self.qps)
            if tokens >= 1:
                tokens -= 1
                await self.redis.hset(key, mapping={"tokens": tokens, "ts": now})
                await self.redis.expire(key, 60)
                return RateDecision(True, int(tokens))
            await self.redis.hset(key, mapping={"tokens": tokens, "ts": now})
            return RateDecision(False, 0, retry_after=1.0 / max(self.qps, 1))
        except Exception:
            # fail-open if Redis unavailable
            return RateDecision(True, self.qps)


class MonthlyQuota:
    """Calendar-month request cap per tenant. Fail-closed when exceeded."""

    def __init__(self, redis_client=None, limit: int = 100_000) -> None:
        self.redis = redis_client
        self.limit = limit
        self._mem: dict[str, int] = {}

    def _key(self, tenant_id: str) -> str:
        month = time.strftime("%Y%m")
        return f"quota:{tenant_id}:{month}"

    async def check_and_increment(self, tenant_id: str) -> None:
        key = self._key(tenant_id)
        if self.redis is not None:
            try:
                count = await self.redis.incr(key)
                if count == 1:
                    await self.redis.expire(key, 60 * 60 * 24 * 32)
                if count > self.limit:
                    raise RateLimitError("Monthly request quota exceeded", detail={"limit": self.limit})
                return
            except RateLimitError:
                raise
            except Exception:
                pass  # fall through to in-memory
        self._mem[key] = self._mem.get(key, 0) + 1
        if self._mem[key] > self.limit:
            raise RateLimitError("Monthly request quota exceeded", detail={"limit": self.limit})
