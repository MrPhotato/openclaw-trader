import { compactText, nonEmptyText, asRecord } from "./misc";
import { formatBandValue, formatPct } from "./currency";

export function strategyRevision(strategy: Record<string, unknown>): number | string | null {
  const raw = strategy["revision_number"];
  if (typeof raw === "number") {
    return raw;
  }
  if (typeof raw === "string" && raw.length > 0) {
    return raw;
  }
  return null;
}

export function shortId(value: string): string {
  return value.length > 12 ? `${value.slice(0, 10)}...` : value;
}

export function strategyIdentity(strategy: Record<string, unknown>): string {
  const revision = strategyRevision(strategy);
  const strategyId = typeof strategy["strategy_id"] === "string" ? shortId(strategy["strategy_id"]) : "待生成";
  return revision ? `第 ${revision} 版 · ${strategyId}` : strategyId;
}

export function strategyBadgeValue(strategy: Record<string, unknown>): string {
  const revision = strategyRevision(strategy);
  if (revision) {
    return `第 ${revision} 版`;
  }
  if (typeof strategy["strategy_id"] === "string" && strategy["strategy_id"].length > 0) {
    return "已就绪";
  }
  return "待生成";
}

export function portfolioModeLabel(value: unknown): string {
  const mode = String(value ?? "idle");
  if (mode === "defensive") {
    return "防守";
  }
  if (mode === "normal") {
    return "常规";
  }
  if (mode === "aggressive") {
    return "进攻";
  }
  if (mode === "idle") {
    return "空闲";
  }
  return mode;
}

export function strategyFocusText(strategy: Record<string, unknown>): string {
  const thesis = typeof strategy["portfolio_thesis"] === "string" ? strategy["portfolio_thesis"] : "";
  if (!thesis) {
    return "PM 还没有正式提交策略。";
  }
  return compactText(thesis, 96);
}

export function directionLabel(value: unknown): string {
  const direction = String(value ?? "flat");
  if (direction === "long") {
    return "做多";
  }
  if (direction === "short") {
    return "做空";
  }
  return "观望";
}

export function stateLabel(value: unknown): string {
  const state = String(value ?? "watch");
  if (state === "active") {
    return "主动跟踪";
  }
  if (state === "watch") {
    return "观察";
  }
  if (state === "disabled") {
    return "停用";
  }
  return state;
}

export function summarizeTarget(item: Record<string, unknown>, band: unknown[]): string {
  const min = formatBandValue(band[0]);
  const max = formatBandValue(band[1]);
  const discretion = formatPct(item.rt_discretion_band_pct);
  return `${stateLabel(item.state)}，目标敞口 ${min} 到 ${max}。RT 机动额度 ${discretion}。`;
}

export function readTargets(strategy: Record<string, unknown>): Array<{ label: string; direction: string; detail: string }> {
  const targets = Array.isArray(strategy.targets) ? strategy.targets : [];
  return targets.slice(0, 6).map((target) => {
    const item = target as Record<string, unknown>;
    const band = Array.isArray(item.target_exposure_band_pct) ? item.target_exposure_band_pct : [];
    return {
      label: String(item.symbol ?? "UNKNOWN"),
      direction: directionLabel(item.direction),
      detail: summarizeTarget(item, band),
    };
  });
}

export function readRechecks(strategy: Record<string, unknown>): Array<{ label: string; detail: string }> {
  const raw = Array.isArray(strategy.scheduled_rechecks) ? strategy.scheduled_rechecks : [];
  return raw.slice(0, 6).map((item, index) => {
    const record = asRecord(item) ?? {};
    return {
      label: `复核 ${index + 1}`,
      detail: `${nonEmptyText(record.reason, "等待下一轮主线复核")} · ${nonEmptyText(record.recheck_at_utc, "时间未写入")}`,
    };
  });
}
