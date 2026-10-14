# AI Engineer Starter Kit

> Production-grade scaffold for building LLM applications — fork it, `docker compose up`, ship.

**Status:** 🚧 Day 1 complete (LLM router + multi-tenant auth + rate limiting + cost tracking). Day 2 adds RAG + Langfuse + eval. Day 3 adds A/B dashboard + K8s + full docs.

## What it does

A FastAPI backend that gives you the boring-but-critical parts of any AI product, already wired:

- **LLM Router** — classifies each request and routes to the cheapest capable provider (OpenAI / Anthropic), with retry + circuit breaker + mock fallback.
- **Multi-tenant auth** — per-tenant API keys (hashed, never plaintext) and short-lived JWTs, with per-key scopes.
- **Rate limiting** — Redis token-bucket QPS + monthly request quota.
- **Cost tracking** — every call logged with token counts + USD cost, and a **fail-closed** monthly token budget.
- **RAG** (Day 2) — chunk → embed → pgvector → hybrid search → rerank → grounded answer with citations.
- **Prompt versioning + eval** (Day 2) — prompts in the DB, not code; golden-set eval with an A/B compare.
- **Observability** — Langfuse traces (Day 2), structured JSON logs, request-id correlation.

Design principle: **fail-closed**. If the system can't serve a request safely (no provider, budget spent, breaker open), it refuses instead of fabricating or over-billing.

## Quickstart

```bash
cp .env.example .env          # add your OPENAI/ANTHROPIC keys (optional — mock mode works without)
docker compose up --build
# API on http://localhost:8000 — try:
curl -s localhost:8000/health
```

## Try it (mock mode, no keys needed)

```bash
curl -s localhost:8000/v1/chat \
  -H "x-api-key: dev-key-123" -H "content-type: application/json" \
  -d '{"messages":[{"role":"user","content":"hello"}]}'
```

## API (Day 1)

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/health` | none | liveness + provider status |
| POST | `/v1/chat` | api-key / JWT | routed chat + cost breakdown |
| GET | `/v1/usage` | api-key / JWT | per-tenant token/cost summary |

## Development (no Docker)

```bash
cd backend
python -m venv .venv && source .venv/Scripts/activate   # Windows
pip install -e ".[dev]"
pytest -q            # 24 tests, no DB/Redis required
ruff check app tests
```

## Layout

```
backend/     FastAPI app (core/, routers/, services/, db/)
frontend/    Next.js A/B eval dashboard (Day 3)
eval/        golden set + eval runner (Day 2)
k8s/         Kubernetes manifests (Day 3)
```

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for design decisions.

## License

MIT
