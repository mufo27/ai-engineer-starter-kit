# Video Walkthrough Script — AI Engineer Starter Kit

**Target length:** ~2:00–2:15 · **Format:** screen recording + voiceover · **Tone:** confident, concise, engineer-to-engineer.

---

## Before you record (checklist)

- [ ] `cp .env.example .env` and set `GEMINI_API_KEY` (or OpenAI/Anthropic) so the "live" demo works.
- [ ] `docker compose up -d --build` — confirm api `:8000`, web `:3000`, db, redis all healthy.
- [ ] Pre-run `make demo` once so responses are warm and nothing surprises you on camera.
- [ ] Zoom your editor/terminal to ~14px+, hide notifications, use a light theme.
- [ ] Have the GitHub repo tab open (https://github.com/mufo27/ai-engineer-starter-kit).
- [ ] Record in 16:9, 1080p. Keep cursor movements slow.

---

## 0:00 – 0:15 — Hook

**On screen:** GitHub repo home (README with badges + architecture diagram).

**Voiceover:**
> "This is an AI Engineer Starter Kit — a production-grade scaffold for building LLM apps.
> It's not a demo toy: it has a smart multi-provider router, hybrid RAG with citations,
> prompt versioning, an eval harness with a CI quality gate, cost tracking, multi-tenant
> auth, and it deploys with Docker and Helm. Let me show you it actually works."

---

## 0:15 – 0:35 — Architecture

**On screen:** scroll to the Mermaid diagram in the README; hover each box as you name it.

**Voiceover:**
> "Requests flow through a pipeline: auth and scope check, a rate limiter, a monthly quota,
> and a fail-closed budget guard. Then the LLM router classifies the task and picks the
> cheapest capable model — OpenAI, Anthropic, Gemini, or any OpenAI-compatible provider.
> The RAG path embeds the query, does a hybrid vector-plus-keyword search against pgvector,
> reranks, and generates a grounded answer with citations. Everything is traced and metered.
> The one design principle running through all of it: fail-closed — if it can't answer safely,
> it refuses instead of making something up."

---

## 0:35 – 0:50 — Bring it up

**On screen:** terminal — type `docker compose up -d --build`, then `curl localhost:8000/health`.

**Voiceover:**
> "One command brings up the whole stack. Here's the health check — the API is live and it
> tells me which providers are configured." *(show JSON: `providers_enabled: true`)*

---

## 0:50 – 1:10 — Routing + cost

**On screen:** `curl` a `/v1/chat` request; highlight `provider`, `model`, `cost_usd`, `task_type` in the response.

**Voiceover:**
> "A chat request gets auto-classified and routed. Notice the response includes which provider
> and model it chose, the token counts, and the exact cost in dollars — that's the cost middleware
> accounting every call. Add a real API key and it routes to real models; without one it falls
> back to a mock so the whole thing runs offline."

---

## 1:10 – 1:30 — RAG with citations

**On screen:** `POST /v1/documents` (ingest), then `POST /v1/ask` — highlight the answer + `citations`.

**Voiceover:**
> "Now RAG. I ingest a document — it gets chunked, embedded, and stored. Then I ask a question:
> 'What does this store sell and where is it?' The answer comes back grounded in the retrieved
> chunk, with a citation pointing to the exact source and a relevance score — no hallucination,
> and every claim is traceable."

---

## 1:30 – 1:50 — A/B eval dashboard

**On screen:** open `localhost:3000` dashboard → tick "Use live provider" → Run comparison → show winner banner + side-by-side KPIs + per-case table.

**Voiceover:**
> "This is the A/B eval dashboard. I can compare two prompt versions across a golden test set.
> I'll turn on the live provider so it uses the real model, and run it — here the terse prompt
> beats the verbose one on faithfulness, case by case. And the same scoring runs as a CI gate:
> if retrieval quality drops below the threshold, the build fails."

---

## 1:50 – 2:10 — Deploy + close

**On screen:** quick flash of `k8s/helm` folder + the GitHub Actions page showing the pipeline green.

**Voiceover:**
> "It's deploy-ready: a Helm chart with autoscaling and ingress, and a CI pipeline that lints,
> tests, gates on eval, builds images, and deploys to staging. Tests, type checks, and lint all
> pass. It's open-source under MIT — the link is in the description. Thanks for watching."

---

## Recording tips

- Record section-by-section and stitch; don't aim for one perfect take.
- Leave 1s of silence at each cut for clean edits.
- If a command is slow, pre-run it and cut to the output.
- End on the green CI page — it's the strongest "this is real" signal.

## Optional 15s shorter cut (for a top-of-application clip)

> "AI Engineer Starter Kit: a multi-provider LLM router, hybrid RAG with citations, prompt
> versioning, a CI eval gate, cost tracking, and Helm deploys — all tested, all fail-closed.
> Link in the description."
