import type { OverviewData } from "../../lib/types";
import { toNumber, usdCompactText } from "../../lib/format";

type Pill = {
  label: string;
  value: string;
  tone: string;
  rank: number;
  solidBg: string;
  triggeredTone: string;
};

const STATE_RANK: Record<string, number> = {
  normal: 0,
  observe: 1,
  reduce: 2,
  exit: 3,
  breaker: 4,
};

function pickEquity(source: unknown): string | null {
  if (source && typeof source === "object") {
    const rec = source as Record<string, unknown>;
    const equity = rec.equity_usd;
    if (equity === null || equity === undefined) {
      return null;
    }
    const n = toNumber(equity);
    return n === null ? null : usdCompactText(n);
  }
  return null;
}

function resolveRank(state: string | null | undefined): number {
  if (!state) return 0;
  return STATE_RANK[state.toLowerCase()] ?? 0;
}

/**
 * Portfolio-level (not per-coin) risk envelope shown as 4 small pills that
 * match the granularity pills in size. Colors escalate green → yellow →
 * orange → red to mirror the drawdown ladder. The backend reports a sticky
 * `state` (the day's worst-so-far), so once a line has been crossed it stays
 * marked "已触发" until UTC rollover even if equity recovers — that's the
 * drawdown-ladder semantic (see `portfolio_state_ladder_high` on the
 * `risk_brake_state` asset).
 */
export function RiskThresholdPills(props: { riskOverlay: OverviewData["risk_overlay"] }) {
  const overlay = props.riskOverlay;

  const peak = overlay?.day_peak_equity_usd;
  const peakValue = peak !== null && peak !== undefined ? usdCompactText(peak) : "—";

  const effectiveRank = resolveRank(overlay?.state);

  const pills: Pill[] = [
    {
      label: "当日最高",
      value: peakValue,
      tone: "text-emerald-300",
      rank: -1,
      solidBg: "bg-emerald-400/15 border-emerald-300/40",
      triggeredTone: "text-emerald-200",
    },
    {
      label: "观察线",
      value: pickEquity(overlay?.observe) ?? "—",
      tone: "text-signal",
      rank: 1,
      solidBg: "bg-signal/15 border-signal/50",
      triggeredTone: "text-signal",
    },
    {
      label: "回撤线",
      value: pickEquity(overlay?.reduce) ?? "—",
      tone: "text-ember",
      rank: 2,
      solidBg: "bg-ember/15 border-ember/50",
      triggeredTone: "text-ember",
    },
    {
      label: "退出线",
      value: pickEquity(overlay?.exit) ?? "—",
      tone: "text-red-400",
      rank: 3,
      solidBg: "bg-red-500/15 border-red-400/50",
      triggeredTone: "text-red-300",
    },
  ];

  return (
    <div className="flex flex-wrap gap-2">
      {pills.map((pill) => {
        const triggered = pill.rank > 0 && effectiveRank >= pill.rank;
        const baseClass = triggered
          ? `${pill.solidBg} border`
          : "border border-white/10 bg-white/[0.04] ring-hairline";
        const valueTone = triggered ? pill.triggeredTone : pill.tone;
        return (
          <div
            key={pill.label}
            className={`inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-xs ${baseClass}`}
          >
            <span className={triggered ? "text-slate-300" : "text-slate-500"}>{pill.label}</span>
            <span className={`tabular-nums font-medium ${valueTone}`}>{pill.value}</span>
            {triggered ? (
              <span className={`text-[10px] font-semibold uppercase tracking-wider ${valueTone}`}>已触发</span>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
