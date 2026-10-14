import { IconBeaker, IconCoin, IconDashboard, IconSettings, IconTrace } from "./icons";

const nav = [
  { label: "Dashboard", icon: IconDashboard, active: false },
  { label: "A/B Eval", icon: IconBeaker, active: true },
  { label: "Traces", icon: IconTrace, active: false },
  { label: "Cost", icon: IconCoin, active: false },
  { label: "Settings", icon: IconSettings, active: false },
];

export default function Sidebar() {
  return (
    <aside
      className="hidden md:flex flex-col w-60 shrink-0 border-r"
      style={{ borderColor: "var(--line)", background: "#fff", minHeight: "100vh" }}
    >
      <div className="flex items-center gap-2 px-5 h-16 border-b" style={{ borderColor: "var(--line)" }}>
        <div
          className="w-8 h-8 rounded-lg flex items-center justify-center text-white font-bold"
          style={{ background: "var(--brand)" }}
        >
          K
        </div>
        <div className="leading-tight">
          <div className="font-semibold text-sm">AI Engineer Kit</div>
          <div className="text-xs" style={{ color: "var(--muted)" }}>Eval console</div>
        </div>
      </div>
      <nav className="p-3 flex flex-col gap-1">
        {nav.map((item) => {
          const Icon = item.icon;
          return (
            <a
              key={item.label}
              href="#"
              className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors"
              style={{
                background: item.active ? "var(--brand-soft)" : "transparent",
                color: item.active ? "var(--brand-dark)" : "var(--muted)",
                justifyContent: "flex-start",
              }}
            >
              <Icon />
              {item.label}
            </a>
          );
        })}
      </nav>
      <div className="mt-auto p-4">
        <div className="card p-3 text-xs" style={{ color: "var(--muted)" }}>
          <div className="flex items-center gap-2 font-semibold" style={{ color: "var(--ink)" }}>
            <span className="w-2 h-2 rounded-full" style={{ background: "var(--brand)" }} /> Backend online
          </div>
          <div className="mt-1">FastAPI · pgvector · Redis</div>
        </div>
      </div>
    </aside>
  );
}
