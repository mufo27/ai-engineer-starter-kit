"""Google Gemini provider (native generateContent REST API via httpx).

Deliberately uses raw REST instead of the google-genai SDK: keeps the dependency
surface small and makes the provider trivially testable (inject an http client).
Docs: https://ai.google.dev/api/generate-content
"""
from __future__ import annotations

import httpx

from app.services.providers.base import ChatMessage, ProviderResult, estimate_tokens

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com"


class GeminiProvider:
    name = "gemini"

    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL, http_client=None) -> None:
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._http = http_client  # optional injected client (for tests); else per-call

    def available(self) -> bool:
        return bool(self._api_key)

    def _payload(self, messages: list[ChatMessage], max_output_tokens: int) -> dict:
        system = next((m.content for m in messages if m.role == "system"), None)
        contents = []
        for m in messages:
            if m.role == "system":
                continue
            role = "model" if m.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m.content}]})
        payload: dict = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_output_tokens},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        return payload

    @staticmethod
    def _extract_text(data: dict) -> str:
        candidates = data.get("candidates") or []
        parts = (candidates[0].get("content") or {}).get("parts") or [] if candidates else []
        return "".join(p.get("text", "") for p in parts)

    async def complete(
        self, messages: list[ChatMessage], *, model: str, max_output_tokens: int = 1024
    ) -> ProviderResult:
        url = f"{self._base_url}/v1beta/models/{model}:generateContent"
        params = {"key": self._api_key}
        payload = self._payload(messages, max_output_tokens)

        if self._http is not None:
            resp = await self._http.post(url, params=params, json=payload)
            resp.raise_for_status()
            data = resp.json()
        else:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(url, params=params, json=payload)
                resp.raise_for_status()
                data = resp.json()

        text = self._extract_text(data)
        usage = data.get("usageMetadata", {})
        prompt = messages[-1].content if messages else ""
        return ProviderResult(
            text=text,
            prompt_tokens=usage.get("promptTokenCount", estimate_tokens(prompt)),
            completion_tokens=usage.get("candidatesTokenCount", estimate_tokens(text)),
            raw={"finish": [c.get("finishReason") for c in data.get("candidates", [])]},
        )

    async def astream(self, messages, *, model, max_output_tokens: int = 1024):
        """Stream text deltas from Gemini's SSE streaming endpoint."""
        import json

        url = f"{self._base_url}/v1beta/models/{model}:streamGenerateContent"
        params = {"key": self._api_key, "alt": "sse"}
        payload = self._payload(messages, max_output_tokens)
        async with httpx.AsyncClient(timeout=120) as client, client.stream(
            "POST", url, params=params, json=payload
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                chunk = line[len("data:"):].strip()
                if not chunk or chunk == "[DONE]":
                    continue
                try:
                    data = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                for part in self._stream_parts(data):
                    yield part

    @staticmethod
    def _stream_parts(data: dict) -> list[str]:
        out = []
        for cand in data.get("candidates", []):
            for part in (cand.get("content") or {}).get("parts", []) or []:
                if part.get("text"):
                    out.append(part["text"])
        return out
