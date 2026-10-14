"""GET /v1/traces — recent request traces (spans + generations + cost) from the
in-memory buffer. Powers the dashboard's Traces view. Newest first.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.deps_auth import PrincipalDep
from app.core.tracing import recent_traces

router = APIRouter(prefix="/v1", tags=["traces"])


@router.get("/traces")
async def traces(principal: PrincipalDep, limit: int = Query(20, ge=1, le=50)) -> dict:
    principal.require("traces")
    items = recent_traces(limit)
    return {"count": len(items), "traces": items}
