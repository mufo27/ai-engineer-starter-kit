"""OpenAI-compatible provider.

Works for OpenAI itself AND any vendor exposing the OpenAI chat-completions
schema (Groq, OpenRouter, DeepSeek, Mistral, Together, Ollama, Azure, ...).
You just pass a different `name` + `base_url` + `api_key`.
"""
from __future__ import annotations

from app.services.providers.base import ChatMessage, ProviderResult, estimate_tokens


class OpenAICompatProvider:
    def __init__(self, name: str, client) -> None:
        self.name = name
        self._client = client

    def available(self) -> bool:
        return self._client is not None

    async def complete(
        self, messages: list[ChatMessage], *, model: str, max_output_tokens: int = 1024
    ) -> ProviderResult:
        resp = await self._client.chat.completions.create(
            model=model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            max_tokens=max_output_tokens,
        )
        usage = getattr(resp, "usage", None)
        ptok = getattr(usage, "prompt_tokens", None) if usage else None
        ctok = getattr(usage, "completion_tokens", None) if usage else None
        text = resp.choices[0].message.content or ""
        prompt = messages[-1].content if messages else ""
        return ProviderResult(
            text=text,
            prompt_tokens=ptok if ptok is not None else estimate_tokens(prompt),
            completion_tokens=ctok if ctok is not None else estimate_tokens(text),
        )

    async def astream(self, messages, *, model, max_output_tokens: int = 1024):
        stream = await self._client.chat.completions.create(
            model=model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            max_tokens=max_output_tokens,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
