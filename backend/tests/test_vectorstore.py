"""In-memory vector store: hybrid retrieval + tenant isolation."""
from __future__ import annotations

import pytest

from app.services.embeddings import MockEmbedder
from app.services.vectorstore import InMemoryVectorStore, StoredChunk


async def _mk(store, tenant, doc, texts):
    emb = MockEmbedder()
    vecs = await emb.embed(texts)
    chunks = [
        StoredChunk(chunk_id=f"{doc}-{i}", document_id=doc, tenant_id=tenant,
                    content=t, embedding=v, meta={"ordinal": i})
        for i, (t, v) in enumerate(zip(texts, vecs, strict=True))
    ]
    await store.add(chunks)


@pytest.mark.asyncio
async def test_hybrid_retrieval_ranks_relevant_first():
    store = InMemoryVectorStore()
    await _mk(store, "t1", "d1", [
        "The mitochondria is the powerhouse of the cell.",
        "Bananas are a yellow tropical fruit.",
        "Cellular respiration occurs in mitochondria.",
    ])
    q = "mitochondria cell respiration"
    [qv] = await MockEmbedder().embed([q])
    results = await store.search(query_vec=qv, query_text=q, tenant_id="t1", k=3)
    assert results
    # top hit should be about mitochondria/cells, not bananas
    assert "mitochondria" in results[0].content.lower() or "cell" in results[0].content.lower()
    assert "banana" not in results[0].content.lower()
    assert results[0].cosine >= 0.0
    assert results[0].lexical > 0.0


@pytest.mark.asyncio
async def test_tenant_isolation():
    store = InMemoryVectorStore()
    await _mk(store, "tA", "dA", ["alpha secret document"])
    await _mk(store, "tB", "dB", ["beta other document"])
    [qv] = await MockEmbedder().embed(["alpha secret"])
    resA = await store.search(query_vec=qv, query_text="alpha secret", tenant_id="tA", k=5)
    resB = await store.search(query_vec=qv, query_text="alpha secret", tenant_id="tB", k=5)
    assert resA and resA[0].document_id == "dA"
    assert resB and resB[0].document_id == "dB"


@pytest.mark.asyncio
async def test_k_limits_results():
    store = InMemoryVectorStore()
    await _mk(store, "t1", "d1", ["one", "two", "three", "four"])
    [qv] = await MockEmbedder().embed(["one"])
    res = await store.search(query_vec=qv, query_text="one", tenant_id="t1", k=2)
    assert len(res) == 2


@pytest.mark.asyncio
async def test_delete_document():
    store = InMemoryVectorStore()
    await _mk(store, "t1", "d1", ["keep this", "delete this"])
    await store.delete_document(document_id="d1", tenant_id="t1")
    [qv] = await MockEmbedder().embed(["keep"])
    assert await store.search(query_vec=qv, query_text="keep", tenant_id="t1", k=5) == []
