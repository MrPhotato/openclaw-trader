import type { AssetRecord, OverviewData } from "../types";
import { asRecord, compactText, nonEmptyText } from "./misc";
import { formatPct, usdText } from "./currency";
import { actionLabel, actualFilledNotional, tradeHeadline } from "./executions";
import { impactLabel, newsCategoryLabel } from "./events";

export function assetTypeLabel(value: string): string {
  const labels: Record<string, string> = {
    strategy: "策略",
    execution_batch: "执行批次",
    execution_result: "执行结果",
    macro_event: "宏观事件",
    macro_daily_memory: "宏观日记忆",
    chief_retro: "Chief 复盘",
    rt_tactical_map: "RT 战术地图",
    owner_summary: "Owner 汇报",
    learning: "学习记录",
    portfolio_snapshot: "组合快照",
  };
  return labels[value] ?? value;
}

export function sessionStatusLabel(value: string): string {
  if (value === "active") {
    return "在线";
  }
  if (value === "running") {
    return "执行中";
  }
  if (value === "idle") {
    return "空闲";
  }
  return "离线";
}

export function summarizeDecisionList(decisions: unknown[]): string {
  if (decisions.length === 0) {
    return "本轮没有新增动作，维持现状。";
  }
  const first = asRecord(decisions[0]);
  if (!first) {
    return "已生成执行决策。";
  }
  const symbol = String(first.symbol ?? "组合");
  const action = actionLabel(first.action);
  const size = formatPct(first.size_pct_of_equity);
  return `${symbol}：${action}，计划使用 ${size} 的预算。`;
}

export function assetPreview(asset?: AssetRecord | null): string {
  if (!asset) {
    return "还没有新的正式记录。";
  }
  if (typeof asset.payload.summary === "string") {
    return compactText(asset.payload.summary, 120);
  }
  if (typeof asset.payload.owner_summary === "string") {
    return compactText(asset.payload.owner_summary, 120);
  }
  if (typeof asset.payload.portfolio_thesis === "string") {
    return `策略判断：${compactText(asset.payload.portfolio_thesis, 88)}`;
  }
  if (Array.isArray(asset.payload.decisions)) {
    return summarizeDecisionList(asset.payload.decisions);
  }
  if (typeof asset.payload.message === "string") {
    return asset.payload.message;
  }
  if (typeof asset.payload.category === "string" && typeof asset.payload.summary === "string") {
    return `${newsCategoryLabel(asset.payload.category)}：${asset.payload.summary}`;
  }
  return "已生成结构化记录，详细链路会在系统归档中继续保留。";
}

export function overviewTimestamp(overview: OverviewData): number {
  const systemUpdatedAt = typeof overview.system?.updated_at === "string" ? overview.system.updated_at : null;
  const timestamp = systemUpdatedAt ? new Date(systemUpdatedAt).getTime() : Number.NaN;
  return Number.isFinite(timestamp) ? timestamp : 0;
}

export function newerOverview(
  streamOverview: OverviewData | undefined,
  queryOverview: OverviewData | undefined,
): OverviewData | undefined {
  if (!streamOverview) {
    return queryOverview;
  }
  if (!queryOverview) {
    return streamOverview;
  }
  return overviewTimestamp(queryOverview) >= overviewTimestamp(streamOverview) ? queryOverview : streamOverview;
}

export function overviewExecutionSummary(records: AssetRecord[]): string {
  if (records.length === 0) {
    return "最近还没有新的正式执行结果。";
  }
  const latest = records[0];
  const headline = tradeHeadline(latest);
  const amount = usdText(actualFilledNotional(latest) ?? latest.payload["notional_usd"]);
  return `${headline}，成交金额 ${amount}。点击展开可看完整回执。`;
}

export function overviewEventSummary(records: AssetRecord[]): string {
  if (records.length === 0) {
    return "当前还没有新的正式高优先事件。";
  }
  const latest = records[0];
  const impact = impactLabel(String(latest.payload["impact_level"] ?? "low"));
  const summary = nonEmptyText(latest.payload["summary"], "暂无摘要。");
  return `${impact}影响：${compactText(summary, 54)} 点击展开查看事件卡片。`;
}
