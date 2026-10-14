"""Cost tracking + budget guardrails.

`UsageTracker` records every LLM call to the usage ledger and enforces a
per-tenant monthly token budget. Budget enforcement is FAIL-CLOSED: once a
tenant is at/over budget, further paid calls are refused (402) rather than
silently accruing cost.

Like the other layers it has a SQL-backed impl and an in-memory impl for tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from app.core.errors import BudgetExhaustedError


@dataclass
class UsageRecord:
    tenant_id: str
    request_id: str
    model: str
    provider: str
    task_type: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: int
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class UsageStore(Protocol):
    async def add(self, record: UsageRecord) -> None: ...
    async def month_tokens(self, tenant_id: str) -> int: ...
    async def month_cost_usd(self, tenant_id: str) -> float: ...


class InMemoryUsageStore:
    def __init__(self) -> None:
        self.records: list[UsageRecord] = []

    async def add(self, record: UsageRecord) -> None:
        self.records.append(record)

    def _month(self, tenant_id: str) -> list[UsageRecord]:
        now = datetime.now(UTC)
        return [
            r for r in self.records
            if r.tenant_id == tenant_id and r.created_at.year == now.year and r.created_at.month == now.month
        ]

    async def month_tokens(self, tenant_id: str) -> int:
        return sum(r.total_tokens for r in self._month(tenant_id))

    async def month_cost_usd(self, tenant_id: str) -> float:
        return round(sum(float(r.cost_usd) for r in self._month(tenant_id)), 6)


class SqlUsageStore:
    async def add(self, record: UsageRecord) -> None:  # pragma: no cover - needs DB
        from sqlalchemy import text

        from app.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO llm_usage
                    (tenant_id, request_id, model, provider, task_type,
                     prompt_tokens, completion_tokens, total_tokens, cost_usd, latency_ms)
                    VALUES (:t,:r,:m,:p,:tt,:pt,:ct,:tot,:c,:l)
                    """
                ),
                {
                    "t": record.tenant_id, "r": record.request_id, "m": record.model,
                    "p": record.provider, "tt": record.task_type, "pt": record.prompt_tokens,
                    "ct": record.completion_tokens, "tot": record.total_tokens,
                    "c": record.cost_usd, "l": record.latency_ms,
                },
            )
            await session.commit()

    async def month_tokens(self, tenant_id: str) -> int:  # pragma: no cover - needs DB
        return await self._scalar(
            "SELECT COALESCE(SUM(total_tokens),0) FROM llm_usage "
            "WHERE tenant_id = :t AND date_trunc('month', created_at) = date_trunc('month', now())",
            tenant_id,
        )

    async def month_cost_usd(self, tenant_id: str) -> float:  # pragma: no cover - needs DB
        return float(
            await self._scalar(
                "SELECT COALESCE(SUM(cost_usd),0) FROM llm_usage "
                "WHERE tenant_id = :t AND date_trunc('month', created_at) = date_trunc('month', now())",
                tenant_id,
            )
        )

    async def _scalar(self, sql: str, tenant_id: str):  # pragma: no cover - needs DB
        from sqlalchemy import text

        from app.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            return (await session.execute(text(sql), {"t": tenant_id})).scalar() or 0


class UsageTracker:
    def __init__(self, store: UsageStore) -> None:
        self.store = store

    async def assert_budget(self, tenant_id: str, budget: int) -> None:
        """Fail-closed: raise if the tenant already consumed its monthly budget."""
        used = await self.store.month_tokens(tenant_id)
        if used >= budget:
            raise BudgetExhaustedError(
                "Monthly token budget exhausted",
                detail={"budget": budget, "used": used},
            )

    async def record(self, record: UsageRecord) -> None:
        await self.store.add(record)

    async def summary(self, tenant_id: str) -> dict:
        return {
            "month_tokens": await self.store.month_tokens(tenant_id),
            "month_cost_usd": await self.store.month_cost_usd(tenant_id),
        }
