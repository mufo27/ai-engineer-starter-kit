"""RAG orchestration: ingestion + grounded question answering with citations.

ingest():  chunk -> embed -> store (vector + lexical).
ask():     embed query -> hybrid retrieve -> rerank -> build grounded prompt
           from the ACTIVE prompt version -> LLM -> return answer + citations.

Every ask records which prompt version was used so eval can A/B versions.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.services.chunking import chunk_text
from app.services.embeddings import EmbeddingProvider
from app.services.llm_router import ChatMessage, LLMRouter, TaskType
from app.services.prompt_store import PromptStore
from app.services.vectorstore import RetrievedChunk, StoredChunk, VectorStore


@dataclass
class Citation:
    marker: int
    chunk_id: str
    document_id: str
    snippet: str
    score: float


@dataclass
class IngestResult:
    document_id: str
    title: str
    chunk_count: int


@dataclass
class AskResult:
    answer: str
    citations: list[Citation] = field(default_factory=list)
    prompt_name: str = "rag_default"
    prompt_version: int = 1
    retrieved: int = 0
    provider: str = ""
    model: str = ""
    task_type: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0


def _snippet(text: str, n: int = 200) -> str:
    return text[:n] + ("…" if len(text) > n else "")


def rerank(query: str, results: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Lightweight rerank: blend retrieval score with exact-phrase presence.

    A production kit would swap this for a cross-encoder (e.g. Cohere Rerank /
    sentence-transformers). The seam is here so it's a drop-in change.
    """
    ql = query.lower()
    for r in results:
        phrase_bonus = 0.1 if any(w in r.content.lower() for w in ql.split() if len(w) > 4) else 0.0
        r.score = r.score + phrase_bonus
    return sorted(results, key=lambda r: r.score, reverse=True)


class RAGService:
    def __init__(
        self,
        *,
        embedder: EmbeddingProvider,
        store: VectorStore,
        prompts: PromptStore,
        router: LLMRouter,
    ) -> None:
        self.embedder = embedder
        self.store = store
        self.prompts = prompts
        self.router = router
        self._docs: dict[str, dict] = {}  # in-memory document index (dev/tests)

    async def ingest(
        self,
        *,
        tenant_id: str,
        title: str,
        text: str,
        source: str | None = None,
        strategy: str = "sentence",
        max_chars: int = 800,
    ) -> IngestResult:
        document_id = str(uuid.uuid4())
        chunks = chunk_text(text, strategy=strategy, max_chars=max_chars)
        if not chunks:
            return IngestResult(document_id=document_id, title=title, chunk_count=0)

        vectors = await self.embedder.embed([c.content for c in chunks])
        stored = [
            StoredChunk(
                chunk_id=str(uuid.uuid4()),
                document_id=document_id,
                tenant_id=tenant_id,
                content=c.content,
                embedding=v,
                meta={"ordinal": c.ordinal, "title": title, "source": source},
            )
            for c, v in zip(chunks, vectors, strict=True)
        ]
        await self.store.add(stored)
        self._docs[document_id] = {
            "document_id": document_id, "title": title, "source": source,
            "tenant_id": tenant_id, "chunk_count": len(chunks),
        }
        return IngestResult(document_id=document_id, title=title, chunk_count=len(chunks))

    def list_documents(self, tenant_id: str) -> list[dict]:
        return [d for d in self._docs.values() if d["tenant_id"] == tenant_id]

    async def ask(
        self,
        *,
        tenant_id: str,
        question: str,
        k: int = 4,
        prompt_name: str = "rag_default",
        prompt_version: int | None = None,
    ) -> AskResult:
        qvec = (await self.embedder.embed([question]))[0]
        raw = await self.store.search(query_vec=qvec, query_text=question, tenant_id=tenant_id, k=k)
        results = rerank(question, raw)[:k]

        citations = [
            Citation(marker=i + 1, chunk_id=r.chunk_id, document_id=r.document_id,
                     snippet=_snippet(r.content), score=round(r.score, 4))
            for i, r in enumerate(results)
        ]
        context = "\n\n".join(f"[{c.marker}] {r.content}" for c, r in zip(citations, results, strict=True)) \
            if results else "(no context found)"

        tpl = await self.prompts.get(name=prompt_name, version=prompt_version)
        if tpl is None:
            # no prompt configured -> fall back to a minimal grounded instruction
            prompt_text = f"Answer using the context.\n\nContext:\n{context}\n\nQuestion: {question}"
            used_name, used_version = prompt_name, 0
        else:
            prompt_text = tpl.render(context=context, question=question)
            used_name, used_version = tpl.name, tpl.version

        llm = await self.router.chat(
            [ChatMessage(role="user", content=prompt_text)], task=TaskType.SIMPLE
        )
        return AskResult(
            answer=llm.text, citations=citations, prompt_name=used_name, prompt_version=used_version,
            retrieved=len(results), provider=llm.provider, model=llm.model, task_type=llm.task_type,
            prompt_tokens=llm.prompt_tokens, completion_tokens=llm.completion_tokens,
            cost_usd=round(llm.cost_usd, 8), latency_ms=llm.latency_ms,
        )

    async def ask_stream(
        self,
        *,
        tenant_id: str,
        question: str,
        k: int = 4,
        prompt_name: str = "rag_default",
        prompt_version: int | None = None,
    ):
        """Yield {'type':'citations'}, then {'type':'delta'}, then {'type':'final','result':AskResult}."""
        qvec = (await self.embedder.embed([question]))[0]
        raw = await self.store.search(query_vec=qvec, query_text=question, tenant_id=tenant_id, k=k)
        results = rerank(question, raw)[:k]
        citations = [
            Citation(marker=i + 1, chunk_id=r.chunk_id, document_id=r.document_id,
                     snippet=_snippet(r.content), score=round(r.score, 4))
            for i, r in enumerate(results)
        ]
        context = "\n\n".join(f"[{c.marker}] {r.content}" for c, r in zip(citations, results, strict=True)) \
            if results else "(no context found)"
        tpl = await self.prompts.get(name=prompt_name, version=prompt_version)
        if tpl is None:
            prompt_text = f"Answer using the context.\n\nContext:\n{context}\n\nQuestion: {question}"
            used_name, used_version = prompt_name, 0
        else:
            prompt_text = tpl.render(context=context, question=question)
            used_name, used_version = tpl.name, tpl.version

        yield {
            "type": "citations",
            "citations": [c.__dict__ for c in citations],
            "retrieved": len(results),
            "prompt_name": used_name,
            "prompt_version": used_version,
        }
        async for ev in self.router.stream_chat([ChatMessage(role="user", content=prompt_text)], task=TaskType.SIMPLE):
            if ev["type"] == "delta":
                yield {"type": "delta", "text": ev["text"]}
            else:
                llm = ev["result"]
                yield {"type": "final", "result": AskResult(
                    answer=llm.text, citations=citations, prompt_name=used_name, prompt_version=used_version,
                    retrieved=len(results), provider=llm.provider, model=llm.model, task_type=llm.task_type,
                    prompt_tokens=llm.prompt_tokens, completion_tokens=llm.completion_tokens,
                    cost_usd=round(llm.cost_usd, 8), latency_ms=llm.latency_ms,
                )}
