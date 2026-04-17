import type { AssetRecord } from "../../lib/types";
import { formatTime, impactLabel, impactTone, newsCategoryLabel, nonEmptyText } from "../../lib/format";

export function MacroEventCard(props: { asset: AssetRecord }) {
  const impact = String(props.asset.payload["impact_level"] ?? "low");
  const refs = Array.isArray(props.asset.payload["source_refs"]) ? props.asset.payload["source_refs"] : [];
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 ring-hairline hover-lift">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium">{newsCategoryLabel(props.asset.payload["category"])}</div>
          <div className="mt-1 text-xs text-slate-500">{formatTime(props.asset.created_at)}</div>
        </div>
        <span className={impactTone(impact)}>{impactLabel(impact)}</span>
      </div>
      <div className="mt-3 text-sm leading-7 text-slate-300">{nonEmptyText(props.asset.payload["summary"], "没有可展示的事件摘要。")}</div>
      <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-slate-500">
        {refs.length ? <span>{refs.length} 个来源已归档</span> : <span>结构化事件已入库</span>}
      </div>
    </div>
  );
}
