import type { AgentLatestData } from "../types";

export function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    month: "short",
    day: "2-digit",
  });
}

export function latestAssetTimestamp(data?: AgentLatestData): string {
  const latest = data?.latest_asset?.created_at ?? data?.session?.last_active_at;
  if (typeof latest === "string" && latest.length > 0) {
    return formatTime(latest);
  }
  return "尚无记录";
}
