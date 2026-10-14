"""LLM router: classification, routing, mock fallback, cost math."""
from __future__ import annotations

import pytest

from app.services.llm_router import (
    CATALOG,
    ChatMessage,
    LLMRouter,
    TaskType,
    classify_task,
    compute_cost,
)


def test_classify_keywords():
    assert classify_task("Classify this sentiment: great!") is TaskType.CLASSIFY
    assert classify_task("Extract the JSON fields please") is TaskType.EXTRACT
    assert classify_task("Analyze the tradeoffs and design an architecture") is TaskType.REASONING
    assert classify_task("hello there") is TaskType.SIMPLE


def test_classify_long_prompt_is_reasoning():
    assert classify_task("x" * 900) is TaskType.REASONING


def test_force_task_overrides():
    assert classify_task("hello", force=TaskType.REASONING) is TaskType.REASONING


@pytest.mark.asyncio
async def test_mock_fallback_when_no_provider(router_mock: LLMRouter):
    res = await router_mock.chat([ChatMessage(role="user", content="hi")])
    assert res.provider == "mock"
    assert res.model == "mock"
    assert res.cost_usd == 0.0
    assert res.total_tokens if hasattr(res, "total_tokens") else True


@pytest.mark.asyncio
async def test_router_reports_actual_task_type(router_mock: LLMRouter):
    # Regression: response must carry the real classification, not a default 'simple'.
    res = await router_mock.chat(
        [ChatMessage(role="user", content="please classify this sentiment: great product")]
    )
    assert res.provider == "mock"          # still mock fallback (no keys)
    assert res.task_type == TaskType.CLASSIFY.value


@pytest.mark.asyncio
async def test_preferred_model_pins(router_mock: LLMRouter):
    res = await router_mock.chat([ChatMessage(role="user", content="hi")], preferred_model="mock")
    assert res.model == "mock"


def test_cost_math():
    spec = CATALOG["gpt-4o"]
    # 1M input + 1M output
    assert compute_cost(spec, 1_000_000, 1_000_000) == pytest.approx(2.5 + 10.0)


@pytest.mark.asyncio
async def test_strict_mode_raises_without_provider():
    strict = LLMRouter(openai_client=None, anthropic_client=None, strict=True)
    from app.core.errors import NoProviderAvailableError

    with pytest.raises(NoProviderAvailableError):
        await strict.chat([ChatMessage(role="user", content="hi")])
