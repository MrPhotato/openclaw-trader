import { compactText, nonEmptyText, rtWorkingPostureLabel, rtWorkingPostureTone } from "../../lib/format";

function RtDecisionBlock(props: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
      <div className="text-[11px] uppercase tracking-[0.22em] text-slate-500">{props.label}</div>
      <div className="mt-2 text-sm leading-7 text-slate-200">{props.value}</div>
    </div>
  );
}

function RtQuickReference(props: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
      <div className="text-[10px] uppercase tracking-[0.22em] text-slate-500">{props.label}</div>
      <div className="mt-1 text-xs leading-5 text-slate-300">{props.value}</div>
    </div>
  );
}

export function RtTacticalCard(props: { coin: Record<string, unknown> }) {
  const posture = rtWorkingPostureLabel(props.coin.working_posture);
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 ring-hairline hover-lift">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-lg font-semibold tracking-tight text-slate-100">{nonEmptyText(props.coin.coin, "UNKNOWN")}</div>
          <div className="mt-1 text-xs text-slate-500">这一栏只看这个币现在偏向怎么做。</div>
        </div>
        <span className={`rounded-full px-3 py-1 text-xs font-medium ${rtWorkingPostureTone(props.coin.working_posture)}`}>{posture}</span>
      </div>
      <div className="mt-4 space-y-4 text-sm leading-7 text-slate-300">
        <RtDecisionBlock label="当前判断" value={compactText(nonEmptyText(props.coin.base_case, "暂无可展示文本。"), 180)} />
        <div className="grid gap-3 sm:grid-cols-2">
          <RtDecisionBlock label="更可能加仓" value={compactText(nonEmptyText(props.coin.preferred_add_condition, "暂无"), 120)} />
          <RtDecisionBlock label="更可能减仓" value={compactText(nonEmptyText(props.coin.preferred_reduce_condition, "暂无"), 120)} />
        </div>
        <RtDecisionBlock
          label="什么时候叫 PM 重看"
          value={compactText(nonEmptyText(props.coin.force_pm_recheck_condition, "暂无"), 140)}
        />
        <div className="grid gap-2 text-xs text-slate-400 sm:grid-cols-2">
          <RtQuickReference label="止盈参考" value={compactText(nonEmptyText(props.coin.reference_take_profit_condition, "暂无"), 80)} />
          <RtQuickReference label="止损参考" value={compactText(nonEmptyText(props.coin.reference_stop_loss_condition, "暂无"), 80)} />
          <RtQuickReference label="禁做区" value={compactText(nonEmptyText(props.coin.no_trade_zone, "暂无"), 80)} />
          <RtQuickReference label="下一步" value={compactText(nonEmptyText(props.coin.next_focus, "继续观察"), 80)} />
        </div>
      </div>
    </div>
  );
}
