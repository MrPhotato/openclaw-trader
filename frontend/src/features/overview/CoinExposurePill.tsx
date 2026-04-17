export function CoinExposurePill(props: {
  coin: string;
  direction?: string;
  directionTone?: "long" | "short" | "flat" | "muted";
  exposure: string;
  strategyExposure?: string;
  share: string;
  strategyShare?: string;
}) {
  const toneClass =
    props.directionTone === "long"
      ? "text-emerald-300"
      : props.directionTone === "short"
        ? "text-rose-300"
        : props.directionTone === "flat"
          ? "text-slate-300"
          : "text-slate-500";
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3 ring-hairline hover-lift">
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-[10px] uppercase tracking-[0.28em] text-slate-500">{props.coin}</div>
        {props.direction ? <div className={`text-[11px] font-medium ${toneClass}`}>{props.direction}</div> : null}
      </div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-2 text-base font-medium tabular-nums text-slate-100">
        <span>{props.exposure}</span>
        {props.strategyExposure ? (
          <span className="text-xs font-normal text-slate-500">/ 策略 {props.strategyExposure}</span>
        ) : null}
      </div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-2 text-xs tabular-nums text-slate-400">
        <span>{props.share}</span>
        {props.strategyShare ? <span className="text-slate-500">/ 策略 {props.strategyShare}</span> : null}
      </div>
    </div>
  );
}
