"""Mock provider — always available, zero cost. Used for tests + dev fallback."""
from __future__ import annotations

from app.services.providers.base import ChatMessage, ProviderResult, estimate_tokens


class MockProvider:
    name = "mock"

    def available(self) -> bool:
        return True

    async def complete(
        self, messages: list[ChatMessage], *, model: str, max_output_tokens: int = 1024
    ) -> ProviderResult:
        prompt = messages[-1].content if messages else ""
        reply = f"[mock:{model}] echo({len(prompt)} chars)"
        return ProviderResult(
            text=reply,
            prompt_tokens=estimate_tokens(prompt),
            completion_tokens=estimate_tokens(reply),
        )
