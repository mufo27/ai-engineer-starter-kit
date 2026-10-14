"""FastAPI application entrypoint.

Wires routers, a global AppError -> JSON handler, structured logging with a
request-id, and a lifespan that swaps in Redis/SQL-backed services when the
environment provides them.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.errors import AppError
from app.core.metrics import METRICS
from app.deps import SERVICES, build_services
from app.routers import ask, chat, documents, metrics, prompts, traces, usage
from app.routers import eval as eval_router

_settings = get_settings()


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            payload["request_id"] = record.request_id
        return json.dumps(payload, ensure_ascii=False)


def _configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(_settings.log_level.upper())


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_logging()
    # Try to attach Redis + SQL-backed services; fall back to in-memory.
    services = SERVICES
    redis_client = None
    try:
        import redis.asyncio as aioredis

        redis_client = aioredis.from_url(_settings.redis_url, decode_responses=True)
        await redis_client.ping()
    except Exception:
        redis_client = None
        logging.getLogger("kit").warning("Redis unavailable -> in-memory rate limiter")

    use_sql = _settings.app_env != "development"
    try:
        services = build_services(redis_client=redis_client, use_sql=use_sql)
    except Exception:
        logging.getLogger("kit").exception("Service build failed -> defaulting to in-memory")
        services = build_services(redis_client=redis_client, use_sql=False)
    app.state.services = services
    app.state.redis = redis_client
    logging.getLogger("kit").info(
        "startup", extra={"request_id": "boot"}
    )
    yield
    if redis_client is not None:
        await redis_client.aclose()


app = FastAPI(
    title="AI Engineer Starter Kit",
    version="0.1.0",
    description="Production-grade LLM router + RAG + cost tracking + multi-tenant auth",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["content-type", "x-api-key", "authorization", "x-request-id"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex
    request.state.request_id = rid
    t0 = time.perf_counter()
    response = await call_next(request)
    response.headers["x-request-id"] = rid
    METRICS.observe_request(request.url.path, response.status_code, time.perf_counter() - t0)
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.to_payload())


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "env": _settings.app_env, "providers_enabled": _settings.any_provider_enabled}


app.include_router(chat.router)
app.include_router(usage.router)
app.include_router(documents.router)
app.include_router(ask.router)
app.include_router(prompts.router)
app.include_router(eval_router.router)
app.include_router(metrics.router)
app.include_router(traces.router)
