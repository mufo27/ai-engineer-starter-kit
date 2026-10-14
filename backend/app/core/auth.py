"""Multi-tenant authentication.

Two credential types:
  1. API key (long-lived, per-tenant) -> resolved to (tenant_id, scopes).
     Raw keys are NEVER stored; only sha256 hash + display prefix.
  2. JWT (short-lived session token) -> carries tenant_id + scopes.

The auth layer is repository-based: `ApiKeyRepository` has a SQL-backed impl and
an in-memory impl for tests (no DB needed to exercise auth logic).
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Protocol

from jose import jwt

from app.config import get_settings
from app.core.errors import AuthError, ForbiddenError, ScopeError

_settings = get_settings()

ALL_SCOPES = {"chat", "ask", "documents", "usage", "eval", "traces"}


@dataclass
class Principal:
    tenant_id: str
    tenant_name: str
    scopes: set[str] = field(default_factory=set)
    auth_kind: str = "api_key"  # or "jwt"

    def require(self, scope: str) -> None:
        if scope not in self.scopes:
            raise ScopeError(f"Missing required scope '{scope}'", detail={"required": scope})


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def issue_jwt(tenant_id: str, tenant_name: str, scopes: list[str]) -> str:
    now = int(time.time())
    payload = {
        "sub": tenant_id,
        "name": tenant_name,
        "scope": " ".join(scopes),
        "iat": now,
        "exp": now + _settings.jwt_ttl_seconds,
    }
    return jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm)


def decode_jwt(token: str) -> Principal:
    try:
        payload = jwt.decode(token, _settings.jwt_secret, algorithms=[_settings.jwt_algorithm])
    except Exception as exc:  # jose raises various errors
        raise AuthError("Invalid or expired token") from exc
    scopes = set(payload.get("scope", "").split())
    return Principal(
        tenant_id=payload["sub"],
        tenant_name=payload.get("name", ""),
        scopes=scopes,
        auth_kind="jwt",
    )


class ApiKeyRepository(Protocol):
    async def lookup(self, raw_key: str) -> Principal | None: ...


class InMemoryApiKeyRepository:
    """Test/dev store. Map hash -> Principal."""

    def __init__(self) -> None:
        self._by_hash: dict[str, Principal] = {}

    def register(self, raw_key: str, principal: Principal) -> None:
        self._by_hash[hash_key(raw_key)] = principal

    async def lookup(self, raw_key: str) -> Principal | None:
        return self._by_hash.get(hash_key(raw_key))


class SqlApiKeyRepository:
    """DB-backed lookup against api_keys + tenants."""

    async def lookup(self, raw_key: str) -> Principal | None:  # pragma: no cover - needs DB
        from sqlalchemy import text

        from app.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            row = (
                await session.execute(
                    text(
                        """
                        SELECT t.id, t.name, k.scopes
                        FROM api_keys k JOIN tenants t ON t.id = k.tenant_id
                        WHERE k.key_hash = :h AND k.is_active AND t.is_active
                        """
                    ),
                    {"h": hash_key(raw_key)},
                )
            ).first()
            if not row:
                return None
            await session.execute(
                text("UPDATE api_keys SET last_used_at = now() WHERE key_hash = :h"), {"h": hash_key(raw_key)}
            )
            await session.commit()
            return Principal(
                tenant_id=str(row.id),
                tenant_name=row.name,
                scopes=set(row.scopes),
                auth_kind="api_key",
            )


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def principal_from_header(authorization: str | None, api_key: str | None, repo: ApiKeyRepository) -> Principal:
    """Resolve a request to a Principal from Authorization / x-api-key headers."""
    if api_key:
        # async lookup handled by caller; here only JWT path is sync
        pass
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise AuthError("Expected 'Authorization: Bearer <token>'")
        return decode_jwt(token)
    raise AuthError("Missing credentials (Bearer JWT or x-api-key)")


def require_scope(principal: Principal, scope: str) -> None:
    if scope not in ALL_SCOPES:
        raise ForbiddenError(f"Unknown scope '{scope}'")
    principal.require(scope)
