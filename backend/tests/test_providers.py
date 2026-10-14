"""Provider registry, Gemini provider (mocked HTTP), and tier-based routing."""
from __future__ import annotations

import pytest

from app.services.llm_router import CATALOG, ChatMessage, LLMRouter, TaskType
from app.services.providers import (
    GeminiProvider,
    MockProvider,
    ProviderRegistry,
)


# ── fakes ─────────────────────────────────────────────────────────
class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class FakeHttpClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    async def post(self, url, params=None, json=None, **kw):
        self.calls.append({"url": url, "params": params, "json": json})
        return FakeResponse(self.payload)


class FakeVendor:
    """Implements the LLMProvider protocol; records the chosen model."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.called_model: str | None = None

    def available(self) -> bool:
        return True

    async def complete(self, messages, *, model, max_output_tokens=1024):
        from app.services.providers.base import ProviderResult

        self.called_model = model
        return ProviderResult(text=f"{self.name}:{model}", prompt_tokens=5, completion_tokens=5)


# ── registry ──────────────────────────────────────────────────────
def test_registry_availability():
    reg = ProviderRegistry([MockProvider()])
    assert reg.is_available("mock")
    assert not reg.is_available("openai")
    assert reg.available_names() == {"mock"}


def test_registry_gemini_available_only_with_key():
    assert GeminiProvider("").available() is False
    assert GeminiProvider("k").available() is True


# ── gemini provider (mocked HTTP) ─────────────────────────────────
@pytest.mark.asyncio
async def test_gemini_parses_response_and_usage():
    payload = {
        "candidates": [{"content": {"parts": [{"text": "Hello from Gemini"}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 11, "candidatesTokenCount": 4},
    }
    http = FakeHttpClient(payload)
    gp = GeminiProvider("test-key", http_client=http)
    res = await gp.complete([ChatMessage(role="user", content="hi")], model="gemini-2.5-flash")
    assert res.text == "Hello from Gemini"
    assert res.prompt_tokens == 11
    assert res.completion_tokens == 4
    # key passed as query param, model in URL
    assert http.calls[0]["params"]["key"] == "test-key"
    assert "gemini-2.5-flash:generateContent" in http.calls[0]["url"]


@pytest.mark.asyncio
async def test_gemini_system_message_maps_to_system_instruction():
    payload = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}], "usageMetadata": {}}
    http = FakeHttpClient(payload)
    gp = GeminiProvider("k", http_client=http)
    await gp.complete(
        [ChatMessage(role="system", content="be terse"), ChatMessage(role="user", content="hi")],
        model="gemini-2.5-flash",
    )
    body = http.calls[0]["json"]
    assert body["systemInstruction"]["parts"][0]["text"] == "be terse"
    assert body["contents"][0]["role"] == "user"  # system excluded from contents


# ── tier-based routing ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_router_picks_cheap_model_for_classify():
    openai_vendor = FakeVendor("openai")
    reg = ProviderRegistry([MockProvider(), openai_vendor])
    router = LLMRouter(reg, strict=False)
    # classify -> target tier 1 -> cheapest tier-1 openai model = gpt-4o-mini
    res = await router.chat([ChatMessage(role="user", content="classify this sentiment")])
    assert res.provider == "openai"
    assert res.model == "gpt-4o-mini"
    assert openai_vendor.called_model == "gpt-4o-mini"
    assert res.task_type == TaskType.CLASSIFY.value


@pytest.mark.asyncio
async def test_router_preferred_model_pins_gemini():
    reg = ProviderRegistry([MockProvider(), FakeVendor("gemini")])
    router = LLMRouter(reg)
    res = await router.chat([ChatMessage(role="user", content="hi")], preferred_model="gemini-3.5-flash-lite")
    assert res.provider == "gemini"
    assert res.model == "gemini-3.5-flash-lite"


def test_catalog_has_gemini_and_examples():
    assert CATALOG["gemini-3.5-flash-lite"].provider == "gemini"
    assert CATALOG["gemini-3.5-flash-lite"].tier == 1
    assert CATALOG["gemini-3.1-pro-preview"].tier == 3
    assert CATALOG["deepseek-chat"].provider == "deepseek"
