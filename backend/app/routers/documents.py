"""POST /v1/documents — RAG ingestion. GET /v1/documents — list for the tenant."""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.deps_auth import PrincipalDep
from app.deps import SERVICES

router = APIRouter(prefix="/v1", tags=["documents"])


class DocumentIn(BaseModel):
    title: str
    text: str = Field(min_length=1)
    source: str | None = None
    strategy: str = "sentence"   # sentence | fixed
    max_chars: int = 800


class DocumentOut(BaseModel):
    document_id: str
    title: str
    chunk_count: int


@router.post("/documents", response_model=DocumentOut)
async def ingest(body: DocumentIn, request: Request, principal: PrincipalDep) -> DocumentOut:
    principal.require("documents")
    services = getattr(request.app.state, "services", SERVICES)
    result = await services.rag.ingest(
        tenant_id=principal.tenant_id, title=body.title, text=body.text,
        source=body.source, strategy=body.strategy, max_chars=body.max_chars,
    )
    return DocumentOut(document_id=result.document_id, title=result.title, chunk_count=result.chunk_count)


@router.get("/documents")
async def list_documents(request: Request, principal: PrincipalDep) -> dict:
    principal.require("documents")
    services = getattr(request.app.state, "services", SERVICES)
    return {"documents": services.rag.list_documents(principal.tenant_id)}
