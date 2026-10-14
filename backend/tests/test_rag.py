"""RAG service end-to-end with mock embedder + mock LLM provider (no DB/network)."""
from __future__ import annotations

import pytest

from app.services.embeddings import MockEmbedder
from app.services.llm_router import LLMRouter
from app.services.prompt_store import InMemoryPromptStore
from app.services.providers import MockProvider, ProviderRegistry
from app.services.rag import RAGService
from app.services.vectorstore import InMemoryVectorStore


@pytest.fixture
def rag() -> RAGService:
    router = LLMRouter(ProviderRegistry([MockProvider()]), strict=False)
    return RAGService(
        embedder=MockEmbedder(),
        store=InMemoryVectorStore(),
        prompts=InMemoryPromptStore(),
        router=router,
    )


@pytest.mark.asyncio
async def test_ingest_returns_chunks(rag: RAGService):
    res = await rag.ingest(
        tenant_id="t1", title="Biology 101",
        text="The mitochondria is the powerhouse of the cell. Cells use ATP for energy.",
    )
    assert res.chunk_count >= 1
    assert res.document_id


@pytest.mark.asyncio
async def test_ask_retrieves_and_cites(rag: RAGService):
    await rag.ingest(tenant_id="t1", title="Biology", text="The mitochondria is the powerhouse of the cell.")
    await rag.ingest(tenant_id="t1", title="Fruit", text="Bananas are yellow and grow on trees.")
    out = await rag.ask(tenant_id="t1", question="What is the powerhouse of the cell?")
    assert out.answer  # mock echoes, but non-empty
    assert out.retrieved >= 1
    assert out.citations[0].marker == 1
    assert out.citations[0].snippet
    # used the active seeded prompt
    assert out.prompt_name == "rag_default" and out.prompt_version == 1
    # routed through mock provider
    assert out.provider == "mock"


@pytest.mark.asyncio
async def test_ask_respects_prompt_version_override(rag: RAGService):
    await rag.ingest(tenant_id="t1", title="Doc", text="Some content here.")
    await rag.prompts.add(name="rag_strict", body="STRICT: {{context}} | Q: {{question}}", created_by="t")
    out = await rag.ask(tenant_id="t1", question="anything?", prompt_name="rag_strict")
    assert out.prompt_name == "rag_strict" and out.prompt_version == 1


@pytest.mark.asyncio
async def test_ask_no_context_still_answers(rag: RAGService):
    out = await rag.ask(tenant_id="empty", question="anything?")
    assert out.retrieved == 0
    assert out.citations == []
    assert out.answer  # mock still returns something


@pytest.mark.asyncio
async def test_documents_listed_per_tenant(rag: RAGService):
    await rag.ingest(tenant_id="tA", title="A", text="alpha content")
    await rag.ingest(tenant_id="tB", title="B", text="beta content")
    docs = rag.list_documents("tA")
    assert len(docs) == 1 and docs[0]["title"] == "A"
