"use client";

import { useCallback, useEffect, useState } from "react";
import KpiCard from "@/components/KpiCard";
import Sidebar, { type Section } from "@/components/Sidebar";
import { IconCheck, IconGlobe, IconMoon, IconSpark, IconSun } from "@/components/icons";
import { getT, type Lang } from "@/lib/i18n";

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
type ChatReply = { reply: string; provider: string; model: string; cost_usd: number; total_tokens: number };

const pct = (n: number) => `${(n * 100).toFixed(0)}%`;

// i18n key prefix per section (dashboard uses the "dash." namespace).
const SECTION_PREFIX: Record<Section, string> = {
  dashboard: "dash", eval: "eval", traces: "traces", cost: "cost", settings: "settings",
};

export default function Home() {
  const [section, setSection] = useState<Section>("eval");
  const [base, setBase] = useState("http://localhost:8000");
  const [apiKey, setApiKey] = useState("dev-key-123");
  const [lang, setLang] = useState<Lang>("en");
  const [theme, setTheme] = useState<"light" | "dark">("light");

  const t = getT(lang);

  // init theme + lang from DOM/localStorage (client only, avoids SSR mismatch)
  useEffect(() => {
    setTheme(document.documentElement.classList.contains("dark") ? "dark" : "light");
    const saved = localStorage.getItem("lang");
    if (saved === "en" || saved === "th") setLang(saved);
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "dark") root.classList.add("dark");
    else root.classList.remove("dark");
    localStorage.setItem("theme", theme);
  }, [theme]);

  useEffect(() => {
    localStorage.setItem("lang", lang);
    document.documentElement.lang = lang;
  }, [lang]);

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

  // dashboard + cost + traces state
  const [health, setHealth] = useState<Health | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [traces, setTraces] = useState<TraceRecord[]>([]);
  const [chatInput, setChatInput] = useState("Explain what this kit does in one sentence.");
  const [chatBusy, setChatBusy] = useState(false);
  const [chat, setChat] = useState<ChatReply | null>(null);

  const authHeaders = useCallback(
    () => ({ "content-type": "application/json", "x-api-key": apiKey }),
    [apiKey]
  );

  const loadHealth = useCallback(async () => {
    try { setHealth(await (await fetch(`${base}/health`)).json()); } catch { setHealth(null); }
  }, [base]);

  const loadUsage = useCallback(async () => {
    try {
      const r = await fetch(`${base}/v1/usage`, { headers: authHeaders() });
      if (!r.ok) throw new Error(String(r.status));
      setUsage(await r.json());
    } catch { setUsage(null); }
  }, [base, authHeaders]);

  const loadTraces = useCallback(async () => {
    try {
      const r = await fetch(`${base}/v1/traces`, { headers: authHeaders() });
      if (!r.ok) throw new Error(String(r.status));
      setTraces((await r.json()).traces ?? []);
    } catch { setTraces([]); }
  }, [base, authHeaders]);

  useEffect(() => {
    if (section === "dashboard") loadHealth();
    if (section === "cost") loadUsage();
    if (section === "traces") loadTraces();
  }, [section, loadHealth, loadUsage, loadTraces]);

  async function runCompare() {
    setLoading(true); setError(null);
    try {
      const res = await fetch(`${base}/v1/eval/compare`, {
        method: "POST", headers: authHeaders(),
        body: JSON.stringify({
          prompt_name: promptName, version_a: versionA, version_b: versionB,
          body_a: bodyA.trim() ? bodyA : null, body_b: bodyB.trim() ? bodyB : null, live,
        }),
      });
      if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
      setResult(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : "request failed");
    } finally { setLoading(false); }
  }

  async function sendChat() {
    if (!chatInput.trim()) return;
    setChatBusy(true); setChat(null);
    try {
      const res = await fetch(`${base}/v1/chat`, {
        method: "POST", headers: authHeaders(),
        body: JSON.stringify({ messages: [{ role: "user", content: chatInput }] }),
      });
      if (!res.ok) throw new Error(String(res.status));
      const d = await res.json();
      setChat({ reply: d.reply, provider: d.provider, model: d.model, cost_usd: d.cost_usd, total_tokens: d.total_tokens });
    } catch { setChat(null); }
    finally { setChatBusy(false); }
  }

  const winner = result
    ? result.summary.a_wins > result.summary.b_wins
      ? `${t("eval.promptA")} (v${result.version_a}) — ${result.summary.a_wins}/${result.cases.length}`
      : result.summary.b_wins > result.summary.a_wins
        ? `${t("eval.promptB")} (v${result.version_b}) — ${result.summary.b_wins}/${result.cases.length}`
        : t("eval.tie")
    : null;

  const chip = (bg: string, fg: string): React.CSSProperties => ({ background: bg, color: fg });

  return (
    <div className="flex">
      <Sidebar active={section} onSelect={setSection} t={t} />
      <main className="flex-1 min-w-0">
        {/* Top bar */}
        <div className="flex items-center justify-end gap-2 px-6 md:px-10 py-3 border-b" style={{ borderColor: "var(--line)", background: "var(--panel)" }}>
          <button className="btn-ghost inline-flex items-center gap-2" onClick={() => setLang(lang === "en" ? "th" : "en")}>
            <IconGlobe /> {lang === "en" ? "EN" : "ไทย"}
          </button>
          <button className="btn-ghost inline-flex items-center gap-2" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
            {theme === "dark" ? <IconSun /> : <IconMoon />} {theme === "dark" ? t("topbar.light") : t("topbar.dark")}
          </button>
        </div>

        <div className="px-6 md:px-10 py-8">
          {/* Header */}
          <header className="mb-6">
            <h1 className="text-2xl font-bold">{t(`${SECTION_PREFIX[section]}.title`)}</h1>
            <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>{t(`${SECTION_PREFIX[section]}.sub`)}</p>
          </header>

          {/* ---------- Dashboard ---------- */}
          {section === "dashboard" && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <KpiCard label={t("dash.apiStatus")} value={health ? health.status : "—"} sub={health ? `${t("dash.env")}: ${health.env}` : t("dash.unreachable")} tone={health?.status === "ok" ? "brand" : "warn"} />
              <KpiCard label={t("dash.providers")} value={health ? (health.providers_enabled ? t("dash.enabled") : t("dash.mockOnly")) : "—"} sub="OpenAI · Anthropic · Gemini · Groq…" />
              <KpiCard label={t("dash.endpoints")} value="12" sub={t("dash.endpointSub")} />

              <div className="card p-5 md:col-span-3">
                <div className="text-sm font-semibold mb-3">{t("dash.stack")}</div>
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
                <button className="btn-primary mt-4" onClick={loadHealth}>{t("dash.refresh")}</button>
              </div>

              {/* Chat playground */}
              <div className="card p-5 md:col-span-3">
                <div className="text-sm font-semibold">{t("dash.playground")}</div>
                <p className="text-xs mt-1 mb-3" style={{ color: "var(--muted)" }}>{t("dash.playgroundHint")}</p>
                <div className="flex gap-2">
                  <input className="field" value={chatInput} onChange={(e) => setChatInput(e.target.value)} placeholder={t("dash.inputPlaceholder")} />
                  <button className="btn-primary inline-flex items-center gap-2 whitespace-nowrap" onClick={sendChat} disabled={chatBusy}>
                    <IconSpark /> {chatBusy ? t("dash.thinking") : t("dash.send")}
                  </button>
                </div>
                {chat && (
                  <div className="mt-4">
                    <div className="card p-4" style={{ background: "var(--surface)" }}>{chat.reply}</div>
                    <div className="text-xs mt-2" style={{ color: "var(--muted)" }}>
                      {t("dash.by")} {chat.provider}:{chat.model} · {chat.total_tokens} tok · ${chat.cost_usd.toFixed(6)}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ---------- A/B Eval ---------- */}
          {section === "eval" && (
            <>
              <section className="card p-5 mb-6">
                <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                  <div className="md:col-span-2">
                    <label className="label">{t("eval.apiBase")}</label>
                    <input className="field" value={base} onChange={(e) => setBase(e.target.value)} />
                  </div>
                  <div>
                    <label className="label">{t("eval.apiKey")}</label>
                    <input className="field" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
                  </div>
                  <div>
                    <label className="label">{t("eval.promptName")}</label>
                    <input className="field" value={promptName} onChange={(e) => setPromptName(e.target.value)} />
                  </div>
                  <div>
                    <label className="label">{t("eval.versionA")}</label>
                    <input className="field" type="number" value={versionA} onChange={(e) => setVersionA(+e.target.value)} />
                  </div>
                  <div>
                    <label className="label">{t("eval.versionB")}</label>
                    <input className="field" type="number" value={versionB} onChange={(e) => setVersionB(+e.target.value)} />
                  </div>
                  <div className="md:col-span-2 flex items-end gap-4">
                    <label className="flex items-center gap-2 text-sm cursor-pointer" style={{ color: "var(--muted)" }}>
                      <input type="checkbox" checked={live} onChange={(e) => setLive(e.target.checked)} />
                      {t("eval.useLive")}
                    </label>
                    <button className="btn-primary inline-flex items-center gap-2" onClick={runCompare} disabled={loading}>
                      <IconSpark /> {loading ? t("eval.running") : t("eval.run")}
                    </button>
                  </div>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
                  <div>
                    <label className="label">{t("eval.bodyA")}</label>
                    <textarea className="field" rows={3} value={bodyA} onChange={(e) => setBodyA(e.target.value)} placeholder={t("eval.bodyAHint")} />
                  </div>
                  <div>
                    <label className="label">{t("eval.bodyB")}</label>
                    <textarea className="field" rows={3} value={bodyB} onChange={(e) => setBodyB(e.target.value)} />
                  </div>
                </div>
                {error && <div className="mt-4 text-sm px-3 py-2 rounded-lg" style={chip("var(--danger-bg)", "var(--danger-fg)")}>{error}</div>}
              </section>

              {result && (
                <>
                  {winner && (
                    <div className="card p-4 mb-6 flex items-center gap-3" style={{ borderColor: "var(--brand)" }}>
                      <div className="w-9 h-9 rounded-full flex items-center justify-center text-white" style={{ background: "var(--brand)" }}><IconCheck /></div>
                      <div>
                        <div className="text-sm font-semibold">{winner}</div>
                        <div className="text-xs" style={{ color: "var(--muted)" }}>
                          A {result.summary.a_wins} · B {result.summary.b_wins} · {t("eval.ties")} {result.summary.ties}
                        </div>
                      </div>
                    </div>
                  )}
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-6">
                    <div className="col-span-2 md:col-span-3 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--muted)" }}>{t("eval.promptA")} · v{result.version_a}</div>
                    <KpiCard label={t("eval.recall")} value={pct(result.aggregate_a.recall_at_k)} tone="brand" />
                    <KpiCard label={t("eval.relevancy")} value={pct(result.aggregate_a.answer_relevancy)} />
                    <KpiCard label={t("eval.faithfulness")} value={pct(result.aggregate_a.faithfulness)} />
                    <div className="col-span-2 md:col-span-3 text-xs font-semibold uppercase tracking-wide mt-2" style={{ color: "var(--muted)" }}>{t("eval.promptB")} · v{result.version_b}</div>
                    <KpiCard label={t("eval.recall")} value={pct(result.aggregate_b.recall_at_k)} tone="brand" />
                    <KpiCard label={t("eval.relevancy")} value={pct(result.aggregate_b.answer_relevancy)} />
                    <KpiCard label={t("eval.faithfulness")} value={pct(result.aggregate_b.faithfulness)} />
                  </div>
                  <section className="card p-0 overflow-hidden">
                    <table className="w-full text-sm">
                      <thead>
                        <tr style={{ background: "var(--surface)" }} className="text-left">
                          <th className="px-4 py-3 font-semibold" style={{ color: "var(--muted)" }}>{t("eval.case")}</th>
                          <th className="px-4 py-3 font-semibold" style={{ color: "var(--muted)" }}>{t("eval.aMetric")}</th>
                          <th className="px-4 py-3 font-semibold" style={{ color: "var(--muted)" }}>{t("eval.bMetric")}</th>
                          <th className="px-4 py-3 font-semibold" style={{ color: "var(--muted)" }}>{t("eval.winner")}</th>
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
                              <span className="inline-block px-2 py-0.5 rounded-full text-xs font-semibold" style={c.winner === "tie" ? chip("var(--chip)", "var(--muted)") : chip("var(--brand-soft)", "var(--brand-dark)")}>
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
              {!result && !loading && <p className="text-sm" style={{ color: "var(--muted)" }}>{t("eval.noResults")}</p>}
            </>
          )}

          {/* ---------- Traces ---------- */}
          {section === "traces" && (
            <div>
              <div className="flex items-center justify-between mb-4">
                <div className="text-sm" style={{ color: "var(--muted)" }}>{traces.length} {t("traces.count")}</div>
                <button className="btn-primary" onClick={loadTraces}>{t("traces.refresh")}</button>
              </div>
              {traces.length === 0 && <div className="card p-6 text-sm" style={{ color: "var(--muted)" }}>{t("traces.empty")}</div>}
              <div className="flex flex-col gap-3">
                {traces.map((tr) => (
                  <div key={tr.trace_id} className="card p-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="px-2 py-0.5 rounded-full text-xs font-semibold" style={chip("var(--brand-soft)", "var(--brand-dark)")}>{tr.name}</span>
                        <span className="text-xs font-mono" style={{ color: "var(--muted)" }}>{tr.request_id?.slice(0, 12)}</span>
                      </div>
                      <div className="text-xs tabular-nums" style={{ color: "var(--muted)" }}>
                        {tr.duration_ms} ms · {tr.total_tokens} tok · ${tr.total_cost_usd.toFixed(6)}
                      </div>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {tr.spans.map((s, i) => (
                        <span key={`s${i}`} className="px-2 py-1 rounded-lg text-xs" style={chip("var(--chip)", "var(--muted)")}>⤷ {s.name} · {s.ms}ms</span>
                      ))}
                      {tr.generations.map((g, i) => (
                        <span key={`g${i}`} className="px-2 py-1 rounded-lg text-xs" style={chip("var(--gen-bg)", "var(--gen-fg)")}>
                          {g.provider}:{g.model} · {g.prompt_tokens}→{g.completion_tokens} tok · ${g.cost_usd.toFixed(6)}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
              <p className="mt-4 text-xs" style={{ color: "var(--muted)" }}>{t("traces.footer")}</p>
            </div>
          )}

          {/* ---------- Cost ---------- */}
          {section === "cost" && (
            <div>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <KpiCard label={t("cost.tokens")} value={usage ? usage.month_tokens.toLocaleString() : "—"} sub={usage ? `${t("cost.budget")} ${usage.budget_tokens.toLocaleString()}` : ""} />
                <KpiCard label={t("cost.spend")} value={usage ? `$${usage.month_cost_usd.toFixed(6)}` : "—"} tone="brand" />
                <KpiCard label={t("cost.tenant")} value={usage ? usage.tenant_name : "—"} />
              </div>
              {usage && (
                <div className="card p-5 mt-4">
                  <div className="text-sm font-semibold mb-2">{t("cost.circuits")}</div>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(usage.circuits).map(([p, c]) => (
                      <span key={p} className="px-2 py-1 rounded-full text-xs font-semibold" style={c.state === "closed" ? chip("var(--brand-soft)", "var(--brand-dark)") : chip("var(--danger-bg)", "var(--danger-fg)")}>
                        {p}: {c.state}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              <button className="btn-primary mt-4" onClick={loadUsage}>{t("cost.refresh")}</button>
            </div>
          )}

          {/* ---------- Settings ---------- */}
          {section === "settings" && (
            <section className="card p-5 max-w-xl">
              <div className="mb-4">
                <label className="label">{t("settings.apiBase")}</label>
                <input className="field" value={base} onChange={(e) => setBase(e.target.value)} />
              </div>
              <div className="mb-4">
                <label className="label">{t("settings.apiKey")}</label>
                <input className="field" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
              </div>
              <div className="mb-4">
                <label className="label">{t("settings.appearance")}</label>
                <div className="flex gap-2">
                  <button className="btn-ghost inline-flex items-center gap-2" onClick={() => setTheme("light")} style={theme === "light" ? { borderColor: "var(--brand)", color: "var(--ink)" } : {}}>
                    <IconSun /> {t("topbar.light")}
                  </button>
                  <button className="btn-ghost inline-flex items-center gap-2" onClick={() => setTheme("dark")} style={theme === "dark" ? { borderColor: "var(--brand)", color: "var(--ink)" } : {}}>
                    <IconMoon /> {t("topbar.dark")}
                  </button>
                  <button className="btn-ghost inline-flex items-center gap-2" onClick={() => setLang(lang === "en" ? "th" : "en")} style={{ borderColor: "var(--brand)" }}>
                    <IconGlobe /> {lang === "en" ? "English" : "ไทย"}
                  </button>
                </div>
              </div>
              <p className="text-xs" style={{ color: "var(--muted)" }}>{t("settings.note")}</p>
            </section>
          )}
        </div>
      </main>
    </div>
  );
}
