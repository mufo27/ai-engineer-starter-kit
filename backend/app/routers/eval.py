"""POST /v1/eval/compare — A/B test two prompt versions against the golden set.

Powers the dashboard: pick a prompt + two versions (or send two inline bodies),
run the golden set through both, get per-case scores + aggregate + winner.
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.core.deps_auth import PrincipalDep
from app.deps import SERVICES
from app.services.eval import compare_prompts

router = APIRouter(prefix="/v1", tags=["eval"])


class CompareIn(BaseModel):
    prompt_name: str = "rag_default"
    version_a: int = 1
    version_b: int = 1
    body_a: str | None = None   # if set, added as a new version and used for A
    body_b: str | None = None   # if set, added as a new version and used for B


@router.post("/eval/compare")
async def compare(body: CompareIn, request: Request, principal: PrincipalDep) -> dict:
    principal.require("eval")
    services = getattr(request.app.state, "services", SERVICES)
    result = await compare_prompts(
        services.prompts,
        prompt_name=body.prompt_name,
        version_a=body.version_a,
        version_b=body.version_b,
        body_a=body.body_a,
        body_b=body.body_b,
    )
    return asdict(result)
