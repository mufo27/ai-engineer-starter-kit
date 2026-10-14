"use client";

import { useState } from "react";
import KpiCard from "@/components/KpiCard";
import Sidebar from "@/components/Sidebar";
import { IconCheck, IconSpark } from "@/components/icons";

type Metrics = { recall_at_k: number; answer_relevancy: number; faithfulness: number };
type CaseRow = { id: string; question: string; a: Metrics; b: Metrics; winner: "a" | "b" | "tie" };
type Compare = {
  prompt_name: string;
  version_a: number;
  version_b: number;
  cases: CaseRow[];
  aggregate_a: Metrics;
  aggregate_b: Metrics;
  summary: { a_wins: number; b_wins: number; ties: number };
};

const pct = (n: number) => `${(n * 100).toFixed(0)}%`;

export default function Home() {
  const [base, setBase] = useState("http://localhost:8000");
  const [apiKey, setApiKey] = useState("dev-key-123");
  const [promptName, setPromptName] = useState("rag_default");
  const [versionA, setVersionA] = useState(1);
  const [versionB, setVersionB] = useState(1);
  const [bodyA, setBodyA] = useState("");
  const [bodyB, setBodyB] = useState("You are a terse assistant. Answer in <= 15 words using ONLY context.\nContext:\n{{context}}\n\nQuestion: {{question}}\n\nAnswer:");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Compare | null>(null);

  async function run() {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${base}/v1/eval/compare`, {
        method: "POST",
        headers: { "content-type": "application/json", "x-api-key": apiKey },
        body: JSON.stringify({
          prompt_name: promptName,
          version_a: versionA,
          version_b: versionB,
          body_a: bodyA.trim() ? bodyA : null,
          body_b: bodyB.trim() ? bodyB : null,
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
      <Sidebar />
      <main className="flex-1 min-w-0 px-6 md:px-10 py-8">
        <header className="mb-6">
          <h1 className="text-2xl font-bold">A/B Prompt Evaluation</h1>
          <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
            Run the golden set through two prompt versions and compare retrieval + grounding.
          </p>
        </header>

        {/* Config */}
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
            <div className="md:col-span-2 flex items-end">
              <button className="btn-primary inline-flex items-center gap-2" onClick={run} disabled={loading}>
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
            <div className="mt-4 text-sm px-3 py-2 rounded-lg" style={{ background: "#fef3f2", color: "#b42318" }}>
              {error}
            </div>
          )}
        </section>

        {/* Results */}
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
              <div className="col-span-2 md:col-span-3 text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--muted)" }}>
                Prompt A · v{result.version_a}
              </div>
              <KpiCard label="Recall@k" value={pct(result.aggregate_a.recall_at_k)} tone="brand" />
              <KpiCard label="Relevancy" value={pct(result.aggregate_a.answer_relevancy)} />
              <KpiCard label="Faithfulness" value={pct(result.aggregate_a.faithfulness)} />
              <div className="col-span-2 md:col-span-3 text-xs font-semibold uppercase tracking-wide mt-2" style={{ color: "var(--muted)" }}>
                Prompt B · v{result.version_b}
              </div>
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
                        <span
                          className="inline-block px-2 py-0.5 rounded-full text-xs font-semibold"
                          style={{
                            background: c.winner === "tie" ? "#f2f4f3" : "var(--brand-soft)",
                            color: c.winner === "tie" ? "var(--muted)" : "var(--brand-dark)",
                          }}
                        >
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
          <p className="text-sm" style={{ color: "var(--muted)" }}>
            Fill the config and run a comparison to see side-by-side results.
          </p>
        )}
      </main>
    </div>
  );
}
