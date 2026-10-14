"use client";

import { useCallback, useEffect, useState } from "react";
import KpiCard from "@/components/KpiCard";
import Sidebar, { type Section } from "@/components/Sidebar";
import { IconCheck, IconSpark } from "@/components/icons";

type Metrics = { recall_at_k: number; answer_relevancy: number; faithfulness: number };
type CaseRow = { id: string; question: string; a: Metrics; b: Metrics; winner: "a" | "b" | "tie" };
type Compare = {
  prompt_name: string; version_a: number; version_b: number; cases: CaseRow[];
  aggregate_a: Metrics; aggregate_b: Metrics; summary: { a_wins: number; b_wins: number; ties: number };
};
type Health = { status: string; env: string; providers_enabled: boolean };
type Usage = {
  tenant_name: string; budget_tokens: number; month_tokens: number;
  month_cost_usd: number; circuits: Record<string, { state: string }>;
};

type TraceRecord = {
  trace_id: string; name: string; request_id?: string; duration_ms: number;
  total_tokens: number; total_cost_usd: number;
  spans: { name: string; ms: number }[];
  generations: { name: string; model: string; provider: string; prompt_tokens: number; completion_tokens: number; cost_usd: number }[];
};

const pct = (n: number) => `${(n * 100).toFixed(0)}%`;

const HEADERS: Record<Section, { title: string; sub: string }> = {
  dashboard: { title: "Dashboard", sub: "System overview and health of the AI Engineer Starter Kit." },
  eval: { title: "A/B Prompt Evaluation", sub: "Run the golden set through two prompt versions and compare retrieval + grounding." },
  traces: { title: "Traces", sub: "Every chat/ask call is traced (spans + generations) and optionally shipped to Langfuse." },
  cost: { title: "Cost", sub: "Per-tenant token usage, spend, and circuit-breaker health." },
  settings: { title: "Settings", sub: "API connection used by all panels." },
};

export default function Home() {
  const [section, setSection] = useState<Section>("eval");
  const [base, setBase] = useState("http://localhost:8000");
  const [apiKey, setApiKey] = useState("dev-key-123");

  // A/B eval state
  const [promptName, setPromptName] = useState("rag_default");
  const [versionA, setVersionA] = useState(1);
  const [versionB, setVersionB] = useState(1);
  const [bodyA, setBodyA] = useState("");
  const [bodyB, setBodyB] = useState("You are a terse assistant. Answer in <= 15 words using ONLY context.\nContext:\n{{context}}\n\nQuestion: {{question}}\n\nAnswer:");
  const [live, setLive] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Compare | null>(null);

  // dashboard + cost state
  const [health, setHealth] = useState<Health | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [traces, setTraces] = useState<TraceRecord[]>([]);

  const authHeaders = useCallback(
    () => ({ "content-type": "application/json", "x-api-key": apiKey }),
    [apiKey]
  );

  const loadHealth = useCallback(async () => {
    try {
      const r = await fetch(`${base}/health`);
      setHealth(await r.json());
    } catch {
      setHealth(null);
    }
  }, [base]);

  const loadUsage = useCallback(async () => {
    try {
      const r = await fetch(`${base}/v1/usage`, { headers: authHeaders() });
      if (!r.ok) throw new Error(String(r.status));
      setUsage(await r.json());
    } catch {
      setUsage(null);
    }
  }, [base, authHeaders]);

  const loadTraces = useCallback(async () => {
    try {
      const r = await fetch(`${base}/v1/traces`, { headers: authHeaders() });
      if (!r.ok) throw new Error(String(r.status));
      const body = await r.json();
      setTraces(body.traces ?? []);
    } catch {
      setTraces([]);
    }
  }, [base, authHeaders]);

  useEffect(() => {
    if (section === "dashboard") loadHealth();
    if (section === "cost") loadUsage();
    if (section === "traces") loadTraces();
  }, [section, loadHealth, loadUsage, loadTraces]);

  async function runCompare() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${base}/v1/eval/compare`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({
          prompt_name: promptName, version_a: versionA, version_b: versionB,
          body_a: bodyA.trim() ? bodyA : null, body_b: bodyB.trim() ? bodyB : null, live,
        }),
      });
      if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
      setResult((await res.json()) as Compare);
    } catch (e) {
      setError(e instanceof Error ? e.message : "request failed");
    } finally {
      setLoading(false);
    }
  }

  const winner = result
    ? result.summary.a_wins > result.summary.b_wins
      ? `Prompt A (v${result.version_a}) wins ${result.summary.a_wins}/${result.cases.length}`
      : result.summary.b_wins > result.summary.a_wins
        ? `Prompt B (v${result.version_b}) wins ${result.summary.b_wins}/${result.cases.length}`
        : "Tie — no clear winner"
    : null;

  return (
    <div className="flex">
      <Sidebar active={section} onSelect={setSection} />
      <main className="flex-1 min-w-0 px-6 md:px-10 py-8">
        <header className="mb-6">
          <h1 className="text-2xl font-bold">{HEADERS[section].title}</h1>
          <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>{HEADERS[section].sub}</p>
        </header>

        {/* ---------- Dashboard ---------- */}
        {section === "dashboard" && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <KpiCard label="API status" value={health ? health.status : "—"} sub={health ? `env: ${health.env}` : "unreachable"} tone={health?.status === "ok" ? "brand" : "warn"} />
            <KpiCard label="Providers" value={health ? (health.providers_enabled ? "Enabled" : "Mock only") : "—"} sub="OpenAI · Anthropic · Gemini · Groq…" />
            <KpiCard label="Endpoints" value="12" sub="chat · ask · documents · prompts · eval" />
            <div className="card p-5 md:col-span-3">
              <div className="text-sm font-semibold mb-3">Stack</div>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm" style={{ color: "var(--muted)" }}>
                <div>FastAPI + Pydantic v2</div>
                <div>Next.js 14 + Tailwind</div>
                <div>PostgreSQL + pgvector</div>
                <div>Redis (rate limit)</div>
                <div>Langfuse tracing</div>
                <div>Prometheus /metrics</div>
                <div>Docker Compose + Helm</div>
                <div>GitHub Actions CI</div>
              </div>
              <button className="btn-primary mt-4" onClick={loadHealth}>Refresh health</button>
            </div>
          </div>
        )}

        {/* ---------- A/B Eval ---------- */}
        {section === "eval" && (
          <>
            <section className="card p-5 mb-6">
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="md:col-span-2">
                  <label className="label">API base URL</label>
                  <input className="field" value={base} onChange={(e) => setBase(e.target.value)} />
                </div>
                <div>
                  <label className="label">API key</label>
                  <input className="field" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
                </div>
                <div>
                  <label className="label">Prompt name</label>
                  <input className="field" value={promptName} onChange={(e) => setPromptName(e.target.value)} />
                </div>
                <div>
                  <label className="label">Version A</label>
                  <input className="field" type="number" value={versionA} onChange={(e) => setVersionA(+e.target.value)} />
                </div>
                <div>
                  <label className="label">Version B</label>
                  <input className="field" type="number" value={versionB} onChange={(e) => setVersionB(+e.target.value)} />
                </div>
                <div className="md:col-span-2 flex items-end gap-4">
                  <label className="flex items-center gap-2 text-sm cursor-pointer" style={{ color: "var(--muted)" }}>
                    <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
                    Use live provider (real LLM)
                  </label>
                  <button className="btn-primary inline-flex items-center gap-2" onClick={runCompare} disabled={loading}>
                    <IconSpark /> {loading ? "Running…" : "Run comparison"}
                  </button>
                </div>
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                <div>
                  <label className="label">Body A (optional — creates a new version)</label>
                  <textarea className="field" rows={3} value={bodyA} onChange={(e) => setBodyA(e.target.value)} placeholder="leave empty to use version A above" />
                </div>
                <div>
                  <label className="label">Body B (optional — creates a new version)</label>
                  <textarea className="field" rows={3} value={bodyB} onChange={(e) => setBodyB(e.target.value)} />
                </div>
              </div>
              {error && (
                <div className="mt-4 text-sm px-3 py-2 rounded-lg" style={{ background: "#fef3f2", color: "#b42318" }}>{error}</div>
              )}
            </section>

            {result && (
              <>
                {winner && (
                  <div className="card p-4 mb-6 flex items-center gap-3" style={{ borderColor: "var(--brand)" }}>
                    <div className="w-9 h-9 rounded-full flex items-center justify-center text-white" style={{ background: "var(--brand)" }}>
                      <IconCheck />
                    </div>
                    <div>
                      <div className="text-sm font-semibold">{winner}</div>
                      <div className="text-xs" style={{ color: "var(--muted)" }}>
                        A {result.summary.a_wins} · B {result.summary.b_wins} · ties {result.summary.ties}
                      </div>
                    </div>
                  </div>
                )}
                <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
                  <div className="col-span-2 md:col-span-3 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--muted)" }}>Prompt A · v{result.version_a}</div>
                  <KpiCard label="Recall@k" value={pct(result.aggregate_a.recall_at_k)} tone="brand" />
                  <KpiCard label="Relevancy" value={pct(result.aggregate_a.answer_relevancy)} />
                  <KpiCard label="Faithfulness" value={pct(result.aggregate_a.faithfulness)} />
                  <div className="col-span-2 md:col-span-3 text-xs font-semibold uppercase tracking-wide mt-2" style={{ color: "var(--muted)" }}>Prompt B · v{result.version_b}</div>
                  <KpiCard label="Recall@k" value={pct(result.aggregate_b.recall_at_k)} tone="brand" />
                  <KpiCard label="Relevancy" value={pct(result.aggregate_b.answer_relevancy)} />
                  <KpiCard label="Faithfulness" value={pct(result.aggregate_b.faithfulness)} />
                </div>
                <section className="card p-0 overflow-hidden">
                  <table className="w-full text-sm">
                    <thead>
                      <tr style={{ background: "#fbfdfc" }} className="text-left">
                        <th className="px-4 py-3 font-semibold" style={{ color: "var(--muted)" }}>Case</th>
                        <th className="px-4 py-3 font-semibold" style={{ color: "var(--muted)" }}>A recall / faith</th>
                        <th className="px-4 py-3 font-semibold" style={{ color: "var(--muted)" }}>B recall / faith</th>
                        <th className="px-4 py-3 font-semibold" style={{ color: "var(--muted)" }}>Winner</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.cases.map((c) => (
                        <tr key={c.id} className="border-t" style={{ borderColor: "var(--line)" }}>
                          <td className="px-4 py-3">
                            <div className="font-medium">{c.id}</div>
                            <div className="text-xs" style={{ color: "var(--muted)" }}>{c.question}</div>
                          </td>
                          <td className="px-4 py-3 tabular-nums">{pct(c.a.recall_at_k)} / {pct(c.a.faithfulness)}</td>
                          <td className="px-4 py-3 tabular-nums">{pct(c.b.recall_at_k)} / {pct(c.b.faithfulness)}</td>
                          <td className="px-4 py-3">
                            <span className="inline-block px-2 py-0.5 rounded-full text-xs font-semibold" style={{ background: c.winner === "tie" ? "#f2f4f3" : "var(--brand-soft)", color: c.winner === "tie" ? "var(--muted)" : "var(--brand-dark)" }}>
                              {c.winner.toUpperCase()}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </section>
              </>
            )}
            {!result && !loading && (
              <p className="text-sm" style={{ color: "var(--muted)" }}>Fill the config and run a comparison to see side-by-side results.</p>
            )}
          </>
        )}

        {/* ---------- Traces ---------- */}
        {section === "traces" && (
          <div>
            <div className="flex items-center justify-between mb-4">
              <div className="text-sm" style={{ color: "var(--muted)" }}>
                {traces.length} recent trace{traces.length === 1 ? "" : "s"} · newest first
              </div>
              <button className="btn-primary" onClick={loadTraces}>Refresh</button>
            </div>

            {traces.length === 0 && (
              <div className="card p-6 text-sm" style={{ color: "var(--muted)" }}>
                No traces yet. Make a <code>/v1/chat</code> or <code>/v1/ask</code> request (or run an A/B eval) and refresh.
              </div>
            )}

            <div className="flex flex-col gap-3">
              {traces.map((t) => (
                <div key={t.trace_id} className="card p-4">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="px-2 py-0.5 rounded-full text-xs font-semibold" style={{ background: "var(--brand-soft)", color: "var(--brand-dark)" }}>
                        {t.name}
                      </span>
                      <span className="text-xs font-mono" style={{ color: "var(--muted)" }}>{t.request_id?.slice(0, 12)}</span>
                    </div>
                    <div className="text-xs tabular-nums" style={{ color: "var(--muted)" }}>
                      {t.duration_ms} ms · {t.total_tokens} tok · ${t.total_cost_usd.toFixed(6)}
                    </div>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {t.spans.map((s, i) => (
                      <span key={`s${i}`} className="px-2 py-1 rounded-lg text-xs" style={{ background: "#f6f8f7", color: "var(--muted)" }}>
                        ⤷ {s.name} · {s.ms}ms
                      </span>
                    ))}
                    {t.generations.map((g, i) => (
                      <span key={`g${i}`} className="px-2 py-1 rounded-lg text-xs" style={{ background: "#eef6ff", color: "#155e93" }}>
                        {g.provider}:{g.model} · {g.prompt_tokens}→{g.completion_tokens} tok · ${g.cost_usd.toFixed(6)}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            <p className="mt-4 text-xs" style={{ color: "var(--muted)" }}>
              Traces are buffered in-memory (last 50). Set <code>LANGFUSE_*</code> env to also ship them to a Langfuse UI.
            </p>
          </div>
        )}

        {/* ---------- Cost ---------- */}
        {section === "cost" && (
          <div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <KpiCard label="Tokens this month" value={usage ? usage.month_tokens.toLocaleString() : "—"} sub={usage ? `budget ${usage.budget_tokens.toLocaleString()}` : ""} />
              <KpiCard label="Spend this month" value={usage ? `$${usage.month_cost_usd.toFixed(6)}` : "—"} tone="brand" />
              <KpiCard label="Tenant" value={usage ? usage.tenant_name : "—"} />
            </div>
            {usage && (
              <div className="card p-5 mt-4">
                <div className="text-sm font-semibold mb-2">Circuit breakers</div>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(usage.circuits).map(([p, c]) => (
                    <span key={p} className="px-2 py-1 rounded-full text-xs font-semibold" style={{ background: c.state === "closed" ? "var(--brand-soft)" : "#fef3f2", color: c.state === "closed" ? "var(--brand-dark)" : "#b42318" }}>
                      {p}: {c.state}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <button className="btn-primary mt-4" onClick={loadUsage}>Refresh usage</button>
          </div>
        )}

        {/* ---------- Settings ---------- */}
        {section === "settings" && (
          <section className="card p-5 max-w-xl">
            <div className="mb-4">
              <label className="label">API base URL</label>
              <input className="field" value={base} onChange={(e) => setBase(e.target.value)} />
            </div>
            <div className="mb-4">
              <label className="label">API key</label>
              <input className="field" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
            </div>
            <p className="text-xs" style={{ color: "var(--muted)" }}>
              These values are used by the Eval, Cost, and Dashboard panels. Provider keys are set
              server-side in <code>.env</code> — never in the browser.
            </p>
          </section>
        )}
      </main>
    </div>
  );
}
