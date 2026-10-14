"""Auth: JWT round-trip, api-key lookup, scope enforcement."""
from __future__ import annotations

import pytest

from app.core.auth import (
    InMemoryApiKeyRepository,
    Principal,
    decode_jwt,
    hash_key,
    issue_jwt,
    require_scope,
)
from app.core.errors import AuthError, ScopeError


def test_jwt_round_trip():
    token = issue_jwt("t1", "acme", ["chat", "usage"])
    p = decode_jwt(token)
    assert p.tenant_id == "t1"
    assert p.scopes == {"chat", "usage"}
    assert p.auth_kind == "jwt"


def test_jwt_invalid_rejected():
    with pytest.raises(AuthError):
        decode_jwt("not-a-token")


def test_hash_key_stable_and_prefix_hidden():
    h = hash_key("secret-abc")
    assert h == hash_key("secret-abc")
    assert "secret" not in h  # never store plaintext


@pytest.mark.asyncio
async def test_api_key_lookup_hit_miss():
    repo = InMemoryApiKeyRepository()
    repo.register("key-xyz", Principal(tenant_id="t9", tenant_name="x", scopes={"chat"}))
    assert (await repo.lookup("key-xyz")).tenant_id == "t9"
    assert (await repo.lookup("wrong")) is None


def test_scope_enforcement():
    p = Principal(tenant_id="t1", tenant_name="x", scopes={"chat"})
    require_scope(p, "chat")  # ok
    with pytest.raises(ScopeError):
        require_scope(p, "documents")
