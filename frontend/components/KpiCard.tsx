type Tone = "brand" | "neutral" | "warn";

const toneColor: Record<Tone, string> = {
  brand: "var(--brand-dark)",
  neutral: "var(--ink)",
  warn: "#b54708",
};

export default function KpiCard({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: Tone;
}) {
  return (
    <div className="card p-4">
      <div className="text-xs font-semibold uppercase tracking-wide" style={{ color: "var(--muted)" }}>
        {label}
      </div>
      <div className="mt-2 text-2xl font-bold" style={{ color: toneColor[tone] }}>
        {value}
      </div>
      {sub && (
        <div className="mt-1 text-xs" style={{ color: "var(--muted)" }}>
          {sub}
        </div>
      )}
    </div>
  );
}
