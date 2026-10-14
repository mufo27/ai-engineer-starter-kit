"""End-to-end HTTP tests via TestClient (mock provider, in-memory services)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.auth import issue_jwt
from app.main import app


def _client():
    # Ensure the demo api key exists in the shared in-memory repo.
    return TestClient(app)


def test_health():
    with _client() as c:
        r = c.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


def test_chat_requires_auth():
    with _client() as c:
        r = c.post("/v1/chat", json={"messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 401


def test_chat_with_jwt_ok():
    token = issue_jwt("t1", "acme", ["chat"])
    with _client() as c:
        r = c.post(
            "/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"messages": [{"role": "user", "content": "hello world"}]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["provider"] == "mock"
        assert "reply" in body and body["total_tokens"] > 0
        assert "x-request-id" in r.headers


def test_chat_missing_scope_forbidden():
    token = issue_jwt("t1", "acme", ["usage"])  # no chat scope
    with _client() as c:
        r = c.post(
            "/v1/chat",
            headers={"Authorization": f"Bearer {token}"},
            json={"messages": [{"role": "user", "content": "hi"}]},
        )
        assert r.status_code == 403


def test_usage_endpoint_ok():
    token = issue_jwt("t1", "acme", ["usage"])
    with _client() as c:
        r = c.get("/v1/usage", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert "month_tokens" in r.json()
