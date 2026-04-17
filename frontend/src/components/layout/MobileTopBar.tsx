import type { ViewKey } from "../../lib/types";
import { navItems } from "../../features/agents/config";
import { StatusDot, type StatusDotTone } from "../primitives/StatusDot";
import { BrandMark } from "./BrandMark";

export function MobileTopBar(props: {
  activeView: ViewKey;
  onSelect: (view: ViewKey) => void;
  connectionLabel: string;
  connectionTone: StatusDotTone;
}) {
  return (
    <div className="sticky top-0 z-30 flex flex-col gap-3 border-b border-white/5 bg-[rgba(8,17,31,0.86)] px-4 py-3 backdrop-blur-xl lg:hidden">
      <div className="flex items-center justify-between gap-3">
        <BrandMark />
        <div className="flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-slate-200">
          <StatusDot tone={props.connectionTone} pulse={props.connectionTone === "online"} />
          <span className="tabular-nums">{props.connectionLabel}</span>
        </div>
      </div>
      <div className="no-scrollbar -mx-1 flex gap-2 overflow-x-auto px-1">
        {navItems.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            onClick={() => props.onSelect(key)}
            className={`shrink-0 rounded-full px-4 py-2 text-sm transition ${
              props.activeView === key
                ? "bg-ember text-ink shadow-[0_0_14px_rgba(255,125,69,0.4)]"
                : "border border-white/10 bg-white/[0.04] text-slate-200 hover:border-white/20"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
