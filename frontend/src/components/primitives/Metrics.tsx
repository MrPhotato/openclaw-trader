export function MetricBadge(props: { label: string; value: string; tone: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3 ring-hairline hover-lift">
      <div className="text-[10px] uppercase tracking-[0.28em] text-slate-500">{props.label}</div>
      <div className={`mt-2 text-sm font-medium tabular-nums ${props.tone}`}>{props.value}</div>
    </div>
  );
}

export function MetricCard(props: { label: string; value: string; detail: string }) {
  return (
    <div className="glass-panel rounded-[22px] p-4 hover-lift">
      <div className="text-[10px] uppercase tracking-[0.28em] text-slate-500">{props.label}</div>
      <div className="mt-3 text-3xl font-semibold tabular-nums tracking-tight">{props.value}</div>
      <div className="mt-2 text-xs leading-5 text-slate-400">{props.detail}</div>
    </div>
  );
}

export function SummaryPill(props: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3 ring-hairline">
      <div className="text-[10px] uppercase tracking-[0.24em] text-slate-500">{props.label}</div>
      <div className="mt-1 text-lg font-semibold tabular-nums text-slate-100 sm:text-xl">{props.value}</div>
    </div>
  );
}

export function HeroMetric(props: { label: string; value: string; tone: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.05] px-4 py-3 ring-hairline">
      <div className="text-[10px] uppercase tracking-[0.26em] text-slate-500">{props.label}</div>
      <div className={`mt-2 text-sm font-medium tabular-nums ${props.tone}`}>{props.value}</div>
    </div>
  );
}
