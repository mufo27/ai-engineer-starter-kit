"""Embedding providers behind one protocol (mirrors the LLM provider registry).

  - MockEmbedder:    deterministic hashing bag-of-words -> 1536-dim, L2-normalized.
                     Zero network, and cosine similarity tracks shared tokens, so
                     RAG is demoable + unit-testable without any API key.
  - OpenAIEmbedder:  text-embedding-3-small @ 1536 dims.
  - GeminiEmbedder:  gemini-embedding-001, requested at 1536 dims (matches schema).

All return 1536-dim vectors so the pgvector `vector(1536)` column is consistent.
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

EMBEDDING_DIM = 1536
_TOKEN_RE = re.compile(r"[a-zA-Z0-9\u0E00-\u0E7F]+")


class EmbeddingProvider(Protocol):
    name: str
    dim: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class MockEmbedder:
    name = "mock"
    dim = EMBEDDING_DIM

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for t in texts:
            vec = [0.0] * self.dim
            tokens = _TOKEN_RE.findall(t.lower())
            for tok in tokens:
                h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=4).digest(), "big")
                idx = h % self.dim
                vec[idx] += 1.0
            out.append(_normalize(vec))
        return out

    async def embed_one(self, text: str) -> list[float]:
        return (await self.embed([text]))[0]


class OpenAIEmbedder:
    name = "openai"
    dim = EMBEDDING_DIM

    def __init__(self, client, model: str = "text-embedding-3-small") -> None:
        self._client = client
        self._model = model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        resp = await self._client.embeddings.create(model=self._model, input=texts, dimensions=self.dim)
        return [d.embedding for d in resp.data]


class GeminiEmbedder:
    name = "gemini"
    dim = EMBEDDING_DIM

    def __init__(self, api_key: str, base_url: str = "https://generativelanguage.googleapis.com",
                 model: str = "gemini-embedding-001", http_client=None) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._http = http_client

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        url = f"{self._base_url}/v1beta/models/{self._model}:embedContent"
        params = {"key": self._api_key}
        vectors: list[list[float]] = []
        for t in texts:
            payload = {"content": {"parts": [{"text": t}]}, "outputDimensionality": self.dim}
            if self._http is not None:
                resp = await self._http.post(url, params=params, json=payload)
            else:
                async with httpx.AsyncClient(timeout=60) as c:
                    resp = await c.post(url, params=params, json=payload)
            resp.raise_for_status()
            vectors.append(resp.json()["embedding"]["values"])
        return vectors


def build_embedder(settings) -> EmbeddingProvider:
    """Pick an embedder from config; default to mock so RAG always works."""
    if settings.openai_enabled:
        from openai import AsyncOpenAI

        return OpenAIEmbedder(AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url))
    if settings.gemini_enabled:
        return GeminiEmbedder(settings.gemini_api_key, base_url=settings.gemini_base_url)
    return MockEmbedder()
