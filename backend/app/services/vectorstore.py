"""Vector store for RAG with hybrid (cosine + keyword) retrieval.

Two implementations behind one protocol:
  - InMemoryVectorStore: dict-backed, cosine + token-overlap. Used in dev/tests.
  - PgVectorStore:       pgvector cosine (`<=>`) + tsvector rank, blended.

Hybrid score = alpha * cosine + (1 - alpha) * lexical, so exact-term matches and
semantic matches both contribute (the classic RAG recall/precision trade-off).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Protocol

_TOKEN_RE = re.compile(r"[a-zA-Z0-9\u0E00-\u0E7F]+")


@dataclass
class StoredChunk:
    chunk_id: str
    document_id: str
    tenant_id: str
    content: str
    embedding: list[float]
    meta: dict = field(default_factory=dict)


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    content: str
    score: float
    cosine: float
    lexical: float
    meta: dict = field(default_factory=dict)


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def lexical_overlap(query: str, content: str) -> float:
    """Fraction of query tokens present in the chunk (coverage) — cheap BM25 proxy."""
    q = set(_TOKEN_RE.findall(query.lower()))
    if not q:
        return 0.0
    c = set(_TOKEN_RE.findall(content.lower()))
    return len(q & c) / len(q)


class VectorStore(Protocol):
    async def add(self, chunks: list[StoredChunk]) -> None: ...
    async def search(
        self, *, query_vec: list[float], query_text: str, tenant_id: str, k: int
    ) -> list[RetrievedChunk]: ...
    async def delete_document(self, *, document_id: str, tenant_id: str) -> None: ...


class InMemoryVectorStore:
    def __init__(self, alpha: float = 0.6) -> None:
        self._by_tenant: dict[str, list[StoredChunk]] = {}
        self.alpha = alpha

    async def add(self, chunks: list[StoredChunk]) -> None:
        for c in chunks:
            self._by_tenant.setdefault(c.tenant_id, []).append(c)

    async def delete_document(self, *, document_id: str, tenant_id: str) -> None:
        self._by_tenant[tenant_id] = [
            c for c in self._by_tenant.get(tenant_id, []) if c.document_id != document_id
        ]

    async def search(self, *, query_vec: list[float], query_text: str, tenant_id: str, k: int) -> list[RetrievedChunk]:
        scored: list[RetrievedChunk] = []
        for c in self._by_tenant.get(tenant_id, []):
            cos = cosine(query_vec, c.embedding)
            lex = lexical_overlap(query_text, c.content)
            score = self.alpha * cos + (1 - self.alpha) * lex
            scored.append(
                RetrievedChunk(
                    chunk_id=c.chunk_id, document_id=c.document_id, content=c.content,
                    score=score, cosine=cos, lexical=lex, meta=c.meta,
                )
            )
        scored.sort(key=lambda r: r.score, reverse=True)
        return scored[:k]


class PgVectorStore:
    """Postgres + pgvector. Cosine distance + tsvector rank, blended in SQL."""

    def __init__(self, alpha: float = 0.6) -> None:
        self.alpha = alpha

    async def add(self, chunks: list[StoredChunk]) -> None:  # pragma: no cover - needs DB
        from sqlalchemy import text

        from app.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            for c in chunks:
                await session.execute(
                    text(
                        "INSERT INTO chunks (id, document_id, tenant_id, ordinal, content, embedding) "
                        "VALUES (:id, :doc, :tenant, :ord, :content, CAST(:emb AS vector))"
                    ),
                    {
                        "id": c.chunk_id, "doc": c.document_id, "tenant": c.tenant_id,
                        "ord": c.meta.get("ordinal", 0), "content": c.content, "emb": c.embedding,
                    },
                )
            await session.commit()

    async def delete_document(self, *, document_id: str, tenant_id: str) -> None:  # pragma: no cover
        from sqlalchemy import text

        from app.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(
                text("DELETE FROM chunks WHERE document_id = :d AND tenant_id = :t"),
                {"d": document_id, "t": tenant_id},
            )
            await session.commit()

    async def search(
        self, *, query_vec: list[float], query_text: str, tenant_id: str, k: int
    ) -> list[RetrievedChunk]:  # pragma: no cover
        from sqlalchemy import text

        from app.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            rows = (
                await session.execute(
                    text(
                        """
                        SELECT id, document_id, content,
                               1 - (embedding <=> CAST(:qvec AS vector)) AS cosine,
                               ts_rank(ts, plainto_tsquery('simple', :qtext)) AS lex
                        FROM chunks
                        WHERE tenant_id = :tenant
                        ORDER BY (embedding <=> CAST(:qvec AS vector))
                        LIMIT :cand
                        """
                    ),
                    {
                        "qvec": query_vec, "qtext": query_text, "tenant": tenant_id,
                        "cand": max(k * 4, 20),
                    },
                )
            ).all()
        out = [
            RetrievedChunk(
                chunk_id=str(r.id), document_id=str(r.document_id), content=r.content,
                cosine=float(r.cosine), lexical=float(r.lex),
                score=self.alpha * float(r.cosine) + (1 - self.alpha) * float(r.lex),
            )
            for r in rows
        ]
        out.sort(key=lambda r: r.score, reverse=True)
        return out[:k]
