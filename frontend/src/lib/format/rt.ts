import { compactText } from "./misc";
import { usdText } from "./currency";
import { portfolioModeLabel } from "./strategy";

export function rtPortfolioPostureLabel(value: unknown, fallbackMode: unknown): string {
  const posture = String(value ?? "").trim().toLowerCase();
  if (!posture) {
    return `${portfolioModeLabel(fallbackMode)}节奏`;
  }
  if (posture === "normal_staged_build") {
    return "常规推进，分批建仓";
  }
  if (posture === "flat") {
    return "轻仓或空仓，先不主动加风险";
  }
  if (posture === "staged-accumulation") {
    return "顺着主线，分批加仓";
  }
  if (posture === "reduce_only") {
    return "先减风险，不做新的进攻";
  }
  return posture.replace(/[_-]+/g, " ");
}

export function rtWorkingPostureLabel(value: unknown): string {
  const posture = String(value ?? "").trim().toLowerCase();
  if (posture === "staged-accumulation") {
    return "分批加仓";
  }
  if (posture === "priority-reduce" || posture === "reduce-first") {
    return "优先减仓";
  }
  if (posture === "flat-watch") {
    return "继续观察";
  }
  if (posture === "hold-core") {
    return "保留核心仓";
  }
  if (posture === "neutral-hold") {
    return "维持现状";
  }
  if (posture === "watch") {
    return "继续观察";
  }
  if (posture) {
    return posture.replace(/[_-]+/g, " ");
  }
  return "暂无姿态";
}

export function rtWorkingPostureTone(value: unknown): string {
  const posture = String(value ?? "").trim().toLowerCase();
  if (posture.includes("reduce")) {
    return "border border-orange-300/20 bg-orange-300/10 text-orange-100";
  }
  if (posture.includes("accum") || posture.includes("add") || posture.includes("build")) {
    return "border border-emerald-300/20 bg-emerald-300/10 text-emerald-100";
  }
  if (posture.includes("watch") || posture.includes("flat")) {
    return "border border-slate-300/20 bg-slate-300/10 text-slate-100";
  }
  return "border border-white/10 bg-white/[0.06] text-slate-100";
}

export function rtDeskHeadline(brief: Record<string, unknown> | null, latestStrategy: Record<string, unknown>): string {
  const deskFocus = typeof brief?.desk_focus === "string" ? brief.desk_focus : "";
  if (deskFocus) {
    return compactText(deskFocus, 160);
  }
  const mode = portfolioModeLabel(latestStrategy["portfolio_mode"]);
  return `RT 还没写出完整地图，先按 ${mode} 节奏观察最新执行与风险变化。`;
}

export function rtNoviceGuide(brief: Record<string, unknown> | null, latestStrategy: Record<string, unknown>): string {
  const posture = rtPortfolioPostureLabel(brief?.portfolio_posture, latestStrategy["portfolio_mode"]);
  const risk = rtRiskBiasLabel(brief?.risk_bias);
  return `当前整体以${posture}为主。下方 2 张卡分别写清 BTC、ETH 现在更偏向加仓、减仓还是继续观察；如果市场走坏，先按"${compactText(risk, 30)}"这一条执行。`;
}

export function rtStrategyKeyLabel(value: string): string {
  const revision = value.match(/:r(\d+)$/);
  if (revision) {
    return `策略 r${revision[1]}`;
  }
  return compactText(value, 20);
}

export function rtRefreshReasonLabel(value: string): string {
  const normalized = value.trim().toLowerCase();
  const labels: Record<string, string> = {
    pm_strategy_revision: "PM 更新策略后重排",
    execution_followup: "执行后跟进",
    cadence: "班次巡检",
    condition_trigger: "条件触发",
    headline_risk: "事件冲击",
    reduce_only: "只减仓",
    flat_only: "只平仓",
  };
  return labels[normalized] ?? value.replace(/[_-]+/g, " ");
}

export function rtRiskBiasLabel(value: unknown): string {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (!normalized) {
    return "风险状态正常。";
  }
  const labels: Record<string, string> = {
    opportunistic_with_hedges: "机会优先，但保留对冲和回撤保护",
    normal: "风险状态正常，可按策略推进",
    neutral: "风险状态正常，可按策略推进",
    defensive: "偏防守，先控回撤",
    reduce_only: "只减仓，不开新风险",
    flat_only: "只平仓，暂不持新仓",
    risk_on: "可以主动承担风险",
    risk_off: "优先收缩风险",
  };
  return labels[normalized] ?? normalized.replace(/[_-]+/g, " ");
}

export function rtMetadataPills(brief: Record<string, unknown> | null, trigger: Record<string, unknown> | null): string[] {
  const items: string[] = [];
  const strategyKey = typeof brief?.strategy_key === "string" ? brief.strategy_key : "";
  const refreshReason = typeof brief?.map_refresh_reason === "string" ? brief.map_refresh_reason : "";
  const triggerReason = typeof trigger?.reason === "string" ? trigger.reason : "";
  const triggerCoins = Array.isArray(trigger?.coins) ? trigger.coins.filter(Boolean).slice(0, 3) : [];

  if (strategyKey) {
    items.push(`基于 ${rtStrategyKeyLabel(strategyKey)}`);
  }
  if (refreshReason) {
    items.push(`地图刷新：${rtRefreshReasonLabel(refreshReason)}`);
  }
  if (triggerReason) {
    items.push(`触发原因：${rtRefreshReasonLabel(triggerReason)}`);
  }
  if (typeof trigger?.lock_mode === "string" && trigger.lock_mode) {
    items.push(`风险锁：${rtRefreshReasonLabel(trigger.lock_mode)}`);
  }
  if (triggerCoins.length) {
    items.push(`关注：${triggerCoins.map((coin) => String(coin).toUpperCase()).join(" / ")}`);
  }
  return items;
}

export function executionThoughtResultText(result: Record<string, unknown>): string {
  if (result.success === true) {
    return `后来执行成功，成交金额 ${usdText(result.notional_usd)}。`;
  }
  if (typeof result.message === "string" && result.message.trim().length > 0) {
    return compactText(result.message, 90);
  }
  if (result.technical_failure === true) {
    return "后来遇到技术性失败，系统已留下回执。";
  }
  return "后来没有形成明确的执行回执。";
}
