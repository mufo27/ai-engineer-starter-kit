"""Lightweight tracing with an optional Langfuse backend.

We model a request as a Trace containing Spans (work units like "retrieve") and
Generations (LLM calls with token/cost). Two backends:
  - LogBackend:      emits the trace as structured JSON to our logger (default).
  - LangfuseBackend: best-effort POST to Langfuse's public ingestion API; fails
                     open (never breaks a request if Langfuse is down).

This keeps the tracing seam provider-agnostic and testable (inject an http client).
"""
from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class TraceEvent:
    id: str
    type: str            # span | generation
    name: str
    start_ts: float
    end_ts: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> int:
        return int(((self.end_ts or time.time()) - self.start_ts) * 1000)


class Trace:
    def __init__(self, tracer: Tracer, name: str, *, user_id: str | None, metadata: dict | None) -> None:
        self.trace_id = uuid.uuid4().hex
        self.name = name
        self.user_id = user_id
        self.metadata = metadata or {}
        self.start_ts = time.time()
        self.events: list[TraceEvent] = []
        self._tracer = tracer

    @contextmanager
    def span(self, name: str, **metadata: Any):
        ev = TraceEvent(uuid.uuid4().hex, "span", name, time.time(), dict(metadata))
        try:
            yield ev
        finally:
            ev.end_ts = time.time()
            self.events.append(ev)

    def generation(
        self, *, name: str, model: str, provider: str, prompt_tokens: int,
        completion_tokens: int, cost_usd: float, **metadata: Any,
    ) -> None:
        now = time.time()
        self.events.append(TraceEvent(
            uuid.uuid4().hex, "generation", name, now, now,
            {"model": model, "provider": provider, "prompt_tokens": prompt_tokens,
             "completion_tokens": completion_tokens, "cost_usd": cost_usd, **metadata},
        ))

    def end(self) -> None:
        self._tracer._flush(self)


class TracingBackend(Protocol):
    def emit(self, trace: Trace) -> None: ...


class LogBackend:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.log = logger or logging.getLogger("kit.trace")

    def emit(self, trace: Trace) -> None:
        payload = {
            "trace_id": trace.trace_id, "name": trace.name, "user_id": trace.user_id,
            "duration_ms": int((time.time() - trace.start_ts) * 1000),
            "spans": [{"name": e.name, "ms": e.duration_ms, **e.metadata} for e in trace.events if e.type == "span"],
            "generations": [{"name": e.name, **e.metadata} for e in trace.events if e.type == "generation"],
        }
        self.log.info(json.dumps(payload, ensure_ascii=False))


class LangfuseBackend:
    """Best-effort ingestion to a self-hosted/cloud Langfuse. Fails open."""

    def __init__(self, public_key: str, secret_key: str, host: str, http_client=None) -> None:
        self._auth = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
        self._host = host.rstrip("/")
        self._http = http_client

    def _batch(self, trace: Trace) -> list[dict]:
        batch = [{
            "id": trace.trace_id, "type": "trace-create", "timestamp": time.time(),
            "body": {"id": trace.trace_id, "name": trace.name, "userId": trace.user_id, "metadata": trace.metadata},
        }]
        for e in trace.events:
            if e.type == "generation":
                batch.append({"id": e.id, "type": "generation-create", "timestamp": time.time(),
                              "body": {"id": e.id, "traceId": trace.trace_id, "name": e.name,
                                       "startTime": e.start_ts, "endTime": e.end_ts, "model": e.metadata.get("model"),
                                       "usage": {"input": e.metadata.get("prompt_tokens"),
                                                 "output": e.metadata.get("completion_tokens"),
                                                 "totalCost": e.metadata.get("cost_usd")}}})
            else:
                batch.append({"id": e.id, "type": "span-create", "timestamp": time.time(),
                              "body": {"id": e.id, "traceId": trace.trace_id, "name": e.name,
                                       "startTime": e.start_ts, "endTime": e.end_ts, "metadata": e.metadata}})
        return batch

    def emit(self, trace: Trace) -> None:
        try:
            import httpx

            url = f"{self._host}/api/public/ingestion"
            headers = {"Authorization": f"Basic {self._auth}", "content-type": "application/json"}
            body = {"batch": self._batch(trace)}
            client = self._http or httpx
            client.post(url, headers=headers, json=body, timeout=10)
        except Exception:  # never break the request for tracing
            logging.getLogger("kit.trace").warning("langfuse emit failed (ignored)")


class Tracer:
    def __init__(self, backend: TracingBackend) -> None:
        self.backend = backend

    def start(self, name: str, *, user_id: str | None = None, metadata: dict | None = None) -> Trace:
        return Trace(self, name, user_id=user_id, metadata=metadata)

    def _flush(self, trace: Trace) -> None:
        self.backend.emit(trace)


def build_tracer(settings) -> Tracer:
    if settings.langfuse_public_key and settings.langfuse_secret_key:
        return Tracer(LangfuseBackend(
            settings.langfuse_public_key, settings.langfuse_secret_key, settings.langfuse_host
        ))
    return Tracer(LogBackend())
