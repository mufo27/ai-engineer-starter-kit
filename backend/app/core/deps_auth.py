"""Shared FastAPI dependencies: principal resolution + request id."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, Request

from app.core.auth import Principal, decode_jwt
from app.core.errors import AuthError
from app.deps import SERVICES


async def get_principal(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header(alias="x-api-key")] = None,
) -> Principal:
    """Resolve caller to a Principal via x-api-key (preferred) or Bearer JWT."""
    repo = getattr(request.app.state, "services", SERVICES).api_keys
    if x_api_key:
        principal = await repo.lookup(x_api_key)
        if principal is None:
            raise AuthError("Invalid API key")
        return principal
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer" and token:
            return decode_jwt(token)
    raise AuthError("Missing credentials (x-api-key or Bearer JWT)")


def request_id() -> str:
    return uuid.uuid4().hex


PrincipalDep = Annotated[Principal, Depends(get_principal)]
