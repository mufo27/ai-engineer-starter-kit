"""HTTP tests for RAG endpoints: documents, ask, prompts (mock provider)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.auth import issue_jwt
from app.main import app


def _tok(*scopes):
    return {"Authorization": f"Bearer {issue_jwt('t1', 'acme', list(scopes))}"}


def test_ingest_and_ask_flow():
    with TestClient(app) as c:
        r = c.post(
            "/v1/documents",
            headers=_tok("documents"),
            json={"title": "Guide", "text": "The Eiffel Tower is located in Paris, France."},
        )
        assert r.status_code == 200, r.text
        assert r.json()["chunk_count"] >= 1

        r2 = c.post(
            "/v1/ask",
            headers=_tok("ask"),
            json={"question": "Where is the Eiffel Tower?"},
        )
        assert r2.status_code == 200, r2.text
        body = r2.json()
        assert body["provider"] == "mock"
        assert body["retrieved"] >= 1
        assert body["citations"] and body["citations"][0]["marker"] == 1
        assert body["prompt_name"] == "rag_default"


def test_documents_requires_scope():
    with TestClient(app) as c:
        r = c.post("/v1/documents", headers=_tok("ask"), json={"title": "x", "text": "y"})
        assert r.status_code == 403  # has ask, not documents


def test_ask_requires_auth():
    with TestClient(app) as c:
        r = c.post("/v1/ask", json={"question": "hi"})
        assert r.status_code == 401


def test_prompt_versioning_endpoints():
    with TestClient(app) as c:
        r = c.post("/v1/prompts", headers=_tok("documents"), json={"name": "p1", "body": "v1 {{context}} {{question}}"})
        assert r.status_code == 200 and r.json()["version"] == 1
        c.post("/v1/prompts", headers=_tok("documents"), json={"name": "p1", "body": "v2 {{context}} {{question}}"})
        g = c.get("/v1/prompts/p1", headers=_tok("documents"))
        assert g.status_code == 200
        assert g.json()["versions"] == [1, 2]
        a = c.post("/v1/prompts/p1/activate", headers=_tok("documents"), json={"version": 2})
        assert a.status_code == 200 and a.json()["active_version"] == 2
        g2 = c.get("/v1/prompts/p1", headers=_tok("documents"))
        assert g2.json()["active_version"] == 2
