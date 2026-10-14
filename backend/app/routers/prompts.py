"""Prompt versioning endpoints.

  POST /v1/prompts            -> add a new version of a named prompt
  GET  /v1/prompts/{name}     -> list versions + active pointer
  POST /v1/prompts/{name}/activate -> set the active version (rollback/promote)
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.core.deps_auth import PrincipalDep
from app.core.errors import ValidationError
from app.deps import SERVICES

router = APIRouter(prefix="/v1", tags=["prompts"])


class PromptIn(BaseModel):
    name: str
    body: str = Field(min_length=1)


class ActivateIn(BaseModel):
    version: int


@router.post("/prompts")
async def create_prompt(body: PromptIn, request: Request, principal: PrincipalDep) -> dict:
    principal.require("documents")
    services = getattr(request.app.state, "services", SERVICES)
    tpl = await services.prompts.add(name=body.name, body=body.body, created_by=principal.tenant_name)
    return {"name": tpl.name, "version": tpl.version, "variables": tpl.variables}


@router.get("/prompts/{name}")
async def get_prompt(name: str, request: Request, principal: PrincipalDep) -> dict:
    principal.require("documents")
    services = getattr(request.app.state, "services", SERVICES)
    versions = await services.prompts.list_versions(name=name)
    active = await services.prompts.get(name=name)
    if not versions:
        raise ValidationError("No such prompt", detail={"name": name})
    return {
        "name": name,
        "versions": versions,
        "active_version": active.version if active else None,
        "active_body": active.body if active else None,
    }


@router.post("/prompts/{name}/activate")
async def activate(name: str, body: ActivateIn, request: Request, principal: PrincipalDep) -> dict:
    principal.require("documents")
    services = getattr(request.app.state, "services", SERVICES)
    ok = await services.prompts.set_active(name=name, version=body.version)
    if not ok:
        raise ValidationError("Cannot activate unknown version", detail={"name": name, "version": body.version})
    return {"name": name, "active_version": body.version}
