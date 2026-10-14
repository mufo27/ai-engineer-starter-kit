"""Embedding providers: mock lexical behavior + Gemini (mocked HTTP)."""
from __future__ import annotations

import math

import pytest

from app.services.embeddings import EMBEDDING_DIM, GeminiEmbedder, MockEmbedder, build_embedder


def _norm(v):
    return math.sqrt(sum(x * x for x in v))


@pytest.mark.asyncio
async def test_mock_embedder_dim_and_normalized():
    emb = MockEmbedder()
    [vec] = await emb.embed(["hello world"])
    assert len(vec) == EMBEDDING_DIM
    assert _norm(vec) == pytest.approx(1.0, abs=1e-6)


@pytest.mark.asyncio
async def test_mock_embedder_semantic_signal():
    emb = MockEmbedder()
    a, b, c = await emb.embed(["quantum computing research", "quantum computing lab", "banana smoothie recipe"])

    def cos(x, y):
        return sum(p * q for p, q in zip(x, y, strict=True))  # normalized -> dot = cosine

    assert cos(a, b) > cos(a, c)  # shared topic scores higher than unrelated


@pytest.mark.asyncio
async def test_mock_embedder_deterministic():
    emb = MockEmbedder()
    v1 = await emb.embed_one("same text")
    v2 = await emb.embed_one("same text")
    assert v1 == v2


class _FakeResp:
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): pass
    def json(self): return self._p


class _FakeHttp:
    def __init__(self): self.calls = []
    async def post(self, url, params=None, json=None, **kw):
        self.calls.append((url, params, json))
        return _FakeResp({"embedding": {"values": [0.1] * EMBEDDING_DIM}})


@pytest.mark.asyncio
async def test_gemini_embedder_requests_1536_dims():
    http = _FakeHttp()
    ge = GeminiEmbedder("k", http_client=http)
    out = await ge.embed(["hi"])
    assert len(out) == 1 and len(out[0]) == EMBEDDING_DIM
    assert http.calls[0][2]["outputDimensionality"] == EMBEDDING_DIM


def test_build_embedder_defaults_to_mock():
    class _S:
        openai_enabled = False
        gemini_enabled = False
    assert isinstance(build_embedder(_S()), MockEmbedder)
