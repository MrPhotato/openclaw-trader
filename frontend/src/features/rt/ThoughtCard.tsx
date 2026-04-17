import {
  actionLabel,
  asRecord,
  directionLabel,
  executionThoughtResultText,
  formatTime,
  nonEmptyText,
  urgencyLabel,
} from "../../lib/format";

export function ThoughtCard(props: { thought: Record<string, unknown> }) {
  const result = asRecord(props.thought.execution_result);
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 ring-hairline hover-lift">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-slate-100">
            {nonEmptyText(props.thought.symbol, "UNKNOWN")} · {actionLabel(props.thought.action)} · {directionLabel(props.thought.direction)}
          </div>
          <div className="mt-1 text-xs text-slate-500">{formatTime(String(props.thought.generated_at_utc ?? ""))}</div>
        </div>
        <div className="text-xs text-slate-400">{urgencyLabel(props.thought.urgency)}</div>
      </div>
      <div className="mt-3 text-sm leading-7 text-slate-300">
        {nonEmptyText(props.thought.reason, "这轮没有留下额外的判断说明。")}
      </div>
      <div className="mt-3 grid gap-2 text-xs text-slate-400 sm:grid-cols-2">
        <div>止盈参考：{nonEmptyText(props.thought.reference_take_profit_condition, "暂无")}</div>
        <div>止损参考：{nonEmptyText(props.thought.reference_stop_loss_condition, "暂无")}</div>
      </div>
      <div className="mt-3 text-xs text-slate-500">
        {result ? executionThoughtResultText(result) : "执行结果尚未回写，当前只展示当时的判断。"}
      </div>
    </div>
  );
}
