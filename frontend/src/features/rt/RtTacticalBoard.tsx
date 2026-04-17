import type { AgentLatestData } from "../../lib/types";
import { EmptyState } from "../../components/primitives/EmptyState";
import { renderCollection } from "../../components/primitives/Collections";
import {
  asRecord,
  formatTime,
  nonEmptyText,
  readTargets,
  rtDeskHeadline,
  rtMetadataPills,
  rtNoviceGuide,
  rtPortfolioPostureLabel,
  rtRiskBiasLabel,
} from "../../lib/format";
import { RtTacticalCard } from "./RtTacticalCard";

function TacticalMetric(props: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 ring-hairline">
      <div className="text-[10px] uppercase tracking-[0.26em] text-slate-500">{props.label}</div>
      <div className="mt-2 text-sm leading-7 text-slate-100">{props.value}</div>
    </div>
  );
}

export function RtTacticalBoard(props: { data?: AgentLatestData; latestStrategy: Record<string, unknown> }) {
  const brief = asRecord(props.data?.tactical_brief);
  const trigger = asRecord(brief?.trigger);
  const coins = Array.isArray(brief?.coins) ? brief?.coins : [];
  const mapNote = typeof brief?.map_note === "string" ? brief.map_note : "";
  const mapGeneratedAt = typeof brief?.map_generated_at === "string" ? brief.map_generated_at : "";
  const latestMapGeneratedAt = typeof brief?.latest_map_generated_at === "string" ? brief.latest_map_generated_at : "";
  const latestMapRefreshReason =
    typeof brief?.latest_map_refresh_reason === "string" ? brief.latest_map_refresh_reason : "";
  if (!brief && !(props.data?.recent_execution_thoughts?.length || readTargets(props.latestStrategy).length)) {
    return <EmptyState message="RT 还没有形成公开可读的战术板，等第一轮执行或策略输出后会自动出现。" />;
  }

  return (
    <div className="space-y-4">
      {mapNote ? (
        <div className="rounded-2xl border border-amber-300/20 bg-amber-300/10 px-4 py-3 text-sm leading-6 text-amber-100">
          <div>{mapNote}</div>
          {mapGeneratedAt ? (
            <div className="mt-1 text-xs text-amber-100/70">当前地图时间：{formatTime(mapGeneratedAt)}</div>
          ) : null}
          {latestMapGeneratedAt ? (
            <div className="mt-1 text-xs text-amber-100/70">
              最近刷新时间：{formatTime(latestMapGeneratedAt)}
              {latestMapRefreshReason ? ` · ${latestMapRefreshReason}` : ""}
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="rounded-[22px] border border-white/10 bg-white/[0.03] p-4 ring-hairline sm:p-5">
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]">
          <div className="rounded-2xl border border-white/10 bg-white/[0.05] p-4 ring-hairline">
            <div className="text-[10px] uppercase tracking-[0.26em] text-slate-500">这轮在做什么</div>
            <div className="mt-3 text-xl font-semibold leading-8 text-slate-50 sm:text-2xl">
              {rtDeskHeadline(brief, props.latestStrategy)}
            </div>
            <div className="mt-3 text-sm leading-7 text-slate-300">{rtNoviceGuide(brief, props.latestStrategy)}</div>
            <div className="mt-4 flex flex-wrap gap-2">
              {rtMetadataPills(brief, trigger).map((item) => (
                <div
                  key={item}
                  className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-slate-300"
                >
                  {item}
                </div>
              ))}
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
            <TacticalMetric
              label="当前打法"
              value={rtPortfolioPostureLabel(brief?.portfolio_posture, props.latestStrategy["portfolio_mode"])}
            />
            <TacticalMetric label="风险要求" value={rtRiskBiasLabel(brief?.risk_bias)} />
            <TacticalMetric label="下次复看" value={nonEmptyText(brief?.next_review_hint, "等待下一次 cadence。")} />
          </div>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {renderCollection(
          coins as Array<Record<string, unknown>>,
          (coin, index) => <RtTacticalCard key={`${coin.coin ?? "coin"}-${index}`} coin={coin} />,
          "当前还没有按币种拆开的战术摘要。",
        )}
      </div>
    </div>
  );
}
