"""Streaming: router.stream_chat, RAG ask_stream, and the SSE endpoint."""
from __future__ import annotations

import pytest

from app.core.auth import issue_jwt
from app.main import app
from app.services.embeddings import MockEmbedder
from app.services.llm_router import ChatMessage, LLMRouter
from app.services.prompt_store import InMemoryPromptStore
from app.services.providers import MockProvider, ProviderRegistry
from app.services.rag import RAGService
from app.services.vectorstore import InMemoryVectorStore


def _router() -> LLMRouter:
    return LLMRouter(ProviderRegistry([MockProvider()]), strict=False)


@pytest.mark.asyncio
async def test_stream_chat_yields_deltas_and_final():
    events = [ev async for ev in _router().stream_chat([ChatMessage(role="user", content="hello there")])]
    deltas = [e for e in events if e["type"] == "delta"]
    finals = [e for e in events if e["type"] == "final"]
    assert len(deltas) >= 2                      # word-by-word from mock
    assert finals and finals[-1]["result"].provider == "mock"
    assert finals[-1]["result"].task_type == "simple"


@pytest.mark.asyncio
async def test_rag_ask_stream_order():
    router = _router()
    rag = RAGService(embedder=MockEmbedder(), store=InMemoryVectorStore(), prompts=InMemoryPromptStore(), router=router)
    await rag.ingest(tenant_id="t1", title="Doc", text="The Eiffel Tower is in Paris.")
    events = [ev async for ev in rag.ask_stream(tenant_id="t1", question="Where is the Eiffel Tower?")]
    types = [e["type"] for e in events]
    assert types[0] == "citations"
    assert "delta" in types
    assert types[-1] == "final"
    assert events[-1]["result"].retrieved >= 1


def test_ask_stream_endpoint_sse():
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        tok = {"Authorization": f"Bearer {issue_jwt('t1', 'acme', ['documents', 'ask'])}"}
        c.post("/v1/documents", headers=tok, json={"title": "G", "text": "The Eiffel Tower is in Paris, France."})
        with c.stream("POST", "/v1/ask/stream", headers=tok, json={"question": "Where is the Eiffel Tower?"}) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            lines = [ln for ln in r.iter_lines() if ln]
            assert any(ln.startswith("data:") for ln in lines)
            assert any('"type": "final"' in ln or '"type":"final"' in ln for ln in lines)
