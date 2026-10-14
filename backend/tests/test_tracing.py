"""Tracing: LogBackend capture, LangfuseBackend POST (mocked), build_tracer selection."""
from __future__ import annotations

from app.core.tracing import LangfuseBackend, LogBackend, Tracer, build_tracer


class RecordingBackend:
    def __init__(self): self.traces = []
    def emit(self, trace): self.traces.append(trace)


def test_tracer_records_spans_and_generations():
    backend = RecordingBackend()
    tracer = Tracer(backend)
    t = tracer.start("chat", user_id="t1", metadata={"request_id": "r1"})
    with t.span("llm"):
        pass
    t.generation(name="chat", model="m", provider="p", prompt_tokens=3, completion_tokens=5, cost_usd=0.1)
    t.end()
    assert len(backend.traces) == 1
    trace = backend.traces[0]
    kinds = [e.type for e in trace.events]
    assert "span" in kinds and "generation" in kinds
    gen = next(e for e in trace.events if e.type == "generation")
    assert gen.metadata["cost_usd"] == 0.1


def test_log_backend_emits_json(caplog):
    import logging
    with caplog.at_level(logging.INFO, logger="kit.trace"):
        tracer = Tracer(LogBackend())
        t = tracer.start("ask", user_id="t1")
        t.generation(name="ask", model="m", provider="gemini", prompt_tokens=1, completion_tokens=2, cost_usd=0.0)
        t.end()
    assert any("ask" in r.message and "generations" in r.message for r in caplog.records)


class _FakeHttp:
    def __init__(self): self.calls = []
    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append((url, headers, json))

        class R:
            status_code = 200
        return R()


def test_langfuse_backend_posts_ingestion_batch():
    http = _FakeHttp()
    backend = LangfuseBackend("pk", "sk", "http://lf:3000", http_client=http)
    tracer = Tracer(backend)
    t = tracer.start("chat", user_id="t1")
    t.generation(name="chat", model="m", provider="p", prompt_tokens=1, completion_tokens=2, cost_usd=0.3)
    t.end()
    assert http.calls
    url, headers, body = http.calls[0]
    assert url.endswith("/api/public/ingestion")
    assert headers["Authorization"].startswith("Basic ")
    types = [e["type"] for e in body["batch"]]
    assert "trace-create" in types and "generation-create" in types


def test_build_tracer_selection():
    class _NoKeys:
        langfuse_public_key = ""
        langfuse_secret_key = ""
        langfuse_host = "http://x"
    class _Keys:
        langfuse_public_key = "pk"
        langfuse_secret_key = "sk"
        langfuse_host = "http://x"
    assert isinstance(build_tracer(_NoKeys()).backend, LogBackend)
    assert isinstance(build_tracer(_Keys()).backend, LangfuseBackend)


def test_recent_traces_buffer():
    from app.core.tracing import recent_traces

    tracer = Tracer(RecordingBackend())
    t = tracer.start("chat", user_id="t1", metadata={"request_id": "r1"})
    with t.span("llm"):
        pass
    t.generation(name="chat", model="m", provider="p", prompt_tokens=10, completion_tokens=5, cost_usd=0.02)
    t.end()
    buf = recent_traces()
    assert buf and buf[0]["name"] == "chat"
    assert buf[0]["request_id"] == "r1"
    assert buf[0]["total_tokens"] == 15
    assert buf[0]["total_cost_usd"] == 0.02
    assert any(s["name"] == "llm" for s in buf[0]["spans"])


def test_traces_endpoint_returns_data():
    from fastapi.testclient import TestClient

    from app.core.auth import issue_jwt
    from app.main import app

    tok = {"Authorization": f"Bearer {issue_jwt('t1', 'acme', ['chat', 'traces'])}"}
    with TestClient(app) as c:
        c.post("/v1/chat", headers=tok, json={"messages": [{"role": "user", "content": "hi"}]})
        r = c.get("/v1/traces", headers=tok)
        assert r.status_code == 200
        body = r.json()
        assert body["count"] >= 1
        assert body["traces"][0]["name"] == "chat"
