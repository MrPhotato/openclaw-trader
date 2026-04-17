import type { ViewKey } from "../../lib/types";
import { navItems } from "../../features/agents/config";
import { StatusDot, type StatusDotTone } from "../primitives/StatusDot";
import { BrandMark } from "./BrandMark";

export function Sidebar(props: {
  activeView: ViewKey;
  onSelect: (view: ViewKey) => void;
  connectionLabel: string;
  connectionTone: StatusDotTone;
  strategyValue: string;
  activeAgents: number;
  eventCount: number;
}) {
  return (
    <aside className="hidden w-[240px] shrink-0 flex-col border-r border-white/5 bg-gradient-to-b from-white/[0.04] to-transparent px-4 pb-4 pt-5 lg:sticky lg:top-0 lg:flex lg:h-screen">
      <BrandMark />
      <div className="mt-7 flex-1">
        <div className="brand-eyebrow mb-2 px-2 text-slate-500">导航</div>
        <nav className="flex flex-col gap-1">
          {navItems.map(({ key, label }, index) => {
            const active = props.activeView === key;
            return (
              <button
                key={key}
                type="button"
                onClick={() => props.onSelect(key)}
                className={`group relative flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition ${
                  active
                    ? "bg-white/[0.06] text-white"
                    : "text-slate-300 hover:bg-white/[0.04] hover:text-white"
                }`}
              >
                {active ? <span className="nav-indicator" aria-hidden="true" /> : null}
                <span
                  aria-hidden="true"
                  className={`font-mono text-[10px] tracking-wider ${
                    active ? "text-neon" : "text-slate-600 group-hover:text-slate-400"
                  }`}
                >
                  0{index + 1}
                </span>
                <span className="font-medium tracking-tight">{label}</span>
              </button>
            );
          })}
        </nav>
      </div>
      <div className="mt-4 space-y-2 rounded-2xl border border-white/[0.06] bg-white/[0.03] p-3 ring-hairline">
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>链路</span>
          <div className="flex items-center gap-2">
            <StatusDot tone={props.connectionTone} pulse={props.connectionTone === "online"} />
            <span className="tabular-nums">{props.connectionLabel}</span>
          </div>
        </div>
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>策略</span>
          <span className="tabular-nums text-ember">{props.strategyValue}</span>
        </div>
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>席位</span>
          <span className="tabular-nums text-slate-200">{props.activeAgents}/4</span>
        </div>
        <div className="flex items-center justify-between text-xs text-slate-400">
          <span>事件</span>
          <span className="tabular-nums text-slate-200">{props.eventCount} 条</span>
        </div>
      </div>
    </aside>
  );
}
