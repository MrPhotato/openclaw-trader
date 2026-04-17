import type { OverviewData } from "../types";
import { usdCompactText } from "./currency";

export function riskStateLabel(riskOverlay: OverviewData["risk_overlay"]): string {
  const state = String(riskOverlay?.state ?? "normal").toLowerCase();
  if (state === "exit") {
    return "退出保护";
  }
  if (state === "reduce") {
    return "减仓保护";
  }
  if (state === "observe") {
    return "观察区";
  }
  if (state === "fallback") {
    return "回撤线已加载";
  }
  return "风险正常";
}

export function riskStateNarrative(riskOverlay: OverviewData["risk_overlay"], latestPortfolio: Record<string, unknown>): string {
  if (!riskOverlay) {
    return `当前账户余额 ${usdCompactText(latestPortfolio["total_equity_usd"])}，但还没有取到正式风控覆盖层。`;
  }
  const current = usdCompactText(riskOverlay.current_equity_usd);
  const peak = usdCompactText(riskOverlay.day_peak_equity_usd);
  return `今日组合峰值 ${peak}，当前余额 ${current}。黄橙红三条线分别对应观察、减仓与退出。`;
}
