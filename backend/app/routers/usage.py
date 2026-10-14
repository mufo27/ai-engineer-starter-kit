"""GET /v1/usage — per-tenant cost summary + breaker health."""
from __future__ import annotations

from fastapi import APIRouter, Request

from app.config import get_settings
from app.core.deps_auth import PrincipalDep
from app.deps import SERVICES

router = APIRouter(prefix="/v1", tags=["usage"])
_settings = get_settings()


@router.get("/usage")
async def usage(request: Request, principal: PrincipalDep) -> dict:
    principal.require("usage")
    services = getattr(request.app.state, "services", SERVICES)
    summary = await services.usage.summary(principal.tenant_id)
    return {
        "tenant_id": principal.tenant_id,
        "tenant_name": principal.tenant_name,
        "budget_tokens": _settings.default_token_budget,
        **summary,
        "circuits": services.router.breakers.snapshot_all(),
    }
