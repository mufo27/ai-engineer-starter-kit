"""Anthropic provider (native Messages API)."""
from __future__ import annotations

from app.services.providers.base import ChatMessage, ProviderResult, estimate_tokens


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, client) -> None:
        self._client = client

    def available(self) -> bool:
        return self._client is not None

    async def complete(
        self, messages: list[ChatMessage], *, model: str, max_output_tokens: int = 1024
    ) -> ProviderResult:
        system = next((m.content for m in messages if m.role == "system"), None)
        convo = [m for m in messages if m.role != "system"]
        resp = await self._client.messages.create(
            model=model,
            max_tokens=max_output_tokens,
            system=system,
            messages=[{"role": m.role, "content": m.content} for m in convo],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        prompt = messages[-1].content if messages else ""
        return ProviderResult(
            text=text,
            prompt_tokens=getattr(resp.usage, "input_tokens", estimate_tokens(prompt)),
            completion_tokens=getattr(resp.usage, "output_tokens", estimate_tokens(text)),
        )
