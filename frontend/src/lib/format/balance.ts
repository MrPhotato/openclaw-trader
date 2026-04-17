import { toNumber } from "./misc";
import { trimNumber } from "./currency";

export type BalanceGranularity = "15m" | "1h" | "1d";
export type BalancePoint = { label: string; equity: number; createdAtMs: number };

export function balanceWindowLabel(granularity: BalanceGranularity): string {
  if (granularity === "15m") {
    return "15 分钟";
  }
  if (granularity === "1h") {
    return "1 小时";
  }
  return "日线";
}

export function balanceGranularityMs(granularity: BalanceGranularity): number {
  if (granularity === "15m") {
    return 15 * 60 * 1000;
  }
  if (granularity === "1h") {
    return 60 * 60 * 1000;
  }
  return 24 * 60 * 60 * 1000;
}

export function balanceBucketCount(granularity: BalanceGranularity): number {
  if (granularity === "15m") {
    return 96; // 24 hours
  }
  if (granularity === "1h") {
    return 168; // 7 days
  }
  return 30; // 30 days (matches backend daily lookback)
}

export function formatBalanceLabel(value: number, granularity: BalanceGranularity): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  if (granularity === "1d") {
    return date.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
    });
  }
  if (granularity === "1h") {
    return date.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
    });
  }
  return date.toLocaleString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function buildBalanceHistory(
  history: Array<{ created_at: string; total_equity_usd?: string | number | null }>,
  latestPortfolio: Record<string, unknown>,
  granularity: BalanceGranularity,
): BalancePoint[] {
  const intervalMs = balanceGranularityMs(granularity);
  const bucketCount = balanceBucketCount(granularity);
  const rawPoints = history
    .map((record) => {
      const createdAt = record.created_at;
      const createdAtMs = new Date(createdAt).getTime();
      const equity = toNumber(record.total_equity_usd);
      if (Number.isNaN(createdAtMs) || equity === null) {
        return null;
      }
      return {
        equity,
        createdAtMs,
      };
    })
    .filter((item): item is { equity: number; createdAtMs: number } => item !== null)
    .sort((left, right) => left.createdAtMs - right.createdAtMs);

  const fallbackEquity = toNumber(latestPortfolio["total_equity_usd"]);
  if (rawPoints.length === 0 && fallbackEquity === null) {
    return [];
  }

  const now = Date.now();
  const endBucketMs = Math.floor(now / intervalMs) * intervalMs;
  const startBucketMs = endBucketMs - intervalMs * (bucketCount - 1);
  const seededPoints =
    rawPoints.length > 0
      ? rawPoints
      : [
          {
            equity: fallbackEquity ?? 0,
            createdAtMs: now,
          },
        ];

  let pointIndex = 0;
  // null until the first real data point is encountered — buckets before the first
  // real point are skipped so we don't render fabricated carry-backward history.
  let lastEquity: number | null = null;
  const series: BalancePoint[] = [];

  for (let bucketMs = startBucketMs; bucketMs <= endBucketMs; bucketMs += intervalMs) {
    const bucketEndMs = bucketMs + intervalMs - 1;
    while (pointIndex < seededPoints.length && seededPoints[pointIndex].createdAtMs <= bucketEndMs) {
      lastEquity = seededPoints[pointIndex].equity;
      pointIndex += 1;
    }

    // Skip buckets before the first real data point to avoid fake carry-backward lines.
    if (lastEquity === null) {
      continue;
    }

    series.push({
      label: formatBalanceLabel(bucketMs, granularity),
      equity: lastEquity,
      createdAtMs: bucketMs,
    });
  }

  return series.length > 0
    ? series
    : [
        {
          label: formatBalanceLabel(endBucketMs, granularity),
          equity: fallbackEquity ?? 0,
          createdAtMs: endBucketMs,
        },
      ];
}

export function computeBalanceChartWidth(length: number, granularity: BalanceGranularity): number {
  const minWidth = 520;
  const pointWidth = granularity === "15m" ? 22 : granularity === "1h" ? 28 : 48;
  return Math.max(minWidth, length * pointWidth);
}

export function balanceScrollCaption(length: number, granularity: BalanceGranularity): string {
  if (length <= 1) {
    return "等待更多历史快照";
  }
  return `已同步 ${length} 个 ${balanceWindowLabel(granularity)}点。桌面滚轮浏览，移动端左右滑动，只有主图与时间轴会横向滚动。`;
}

export function buildBalanceDomain(points: Array<{ equity: number }>): number[] {
  const values = points.map((point) => point.equity).filter((value) => Number.isFinite(value));
  if (values.length === 0) {
    return [] as number[];
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (Math.abs(max - min) < 0.0001) {
    const padding = Math.max(1, max * 0.01);
    return [min - padding, max + padding];
  }
  const padding = (max - min) * 0.06;
  return [Math.max(0, min - padding), max + padding];
}

export function buildBalanceTicks(points: Array<{ equity: number }>): number[] {
  const domain = buildBalanceDomain(points);
  if (domain.length === 0) {
    return [];
  }
  const [min, max] = domain;
  if (Math.abs(max - min) < 0.0001) {
    return [min];
  }

  const tickCount = 6;
  const step = (max - min) / (tickCount - 1);
  return Array.from({ length: tickCount }, (_, index) => Number((min + step * index).toFixed(4)));
}

export function balanceAxisTickLabel(value: number): string {
  return `$${trimNumber(value)}`;
}

export type DailyChange = {
  pct: number;
  direction: "up" | "down" | "flat";
};

/**
 * Day-over-equity change. Anchors off the earliest portfolio_history
 * snapshot taken today (UTC); if today hasn't been sampled yet, falls
 * back to the most-recent snapshot from before today (yesterday's close).
 * Returns null when there's no usable baseline.
 */
export function computeDailyChange(
  currentEquity: unknown,
  portfolioHistory: Array<{ created_at: string; total_equity_usd?: string | number | null }>,
): DailyChange | null {
  const current = toNumber(currentEquity);
  if (current === null || current <= 0 || portfolioHistory.length === 0) {
    return null;
  }

  const todayUtc = new Date().toISOString().slice(0, 10);
  const parsed = portfolioHistory
    .map((item) => {
      if (typeof item.created_at !== "string" || item.created_at.length < 10) return null;
      const equity = toNumber(item.total_equity_usd);
      if (equity === null || equity <= 0) return null;
      return { createdAt: item.created_at, dateUtc: item.created_at.slice(0, 10), equity };
    })
    .filter((item): item is { createdAt: string; dateUtc: string; equity: number } => item !== null)
    .sort((a, b) => a.createdAt.localeCompare(b.createdAt));

  const todays = parsed.filter((item) => item.dateUtc === todayUtc);
  let baseline: number | null = null;
  if (todays.length > 0) {
    baseline = todays[0].equity;
  } else {
    const earlier = parsed.filter((item) => item.dateUtc < todayUtc);
    if (earlier.length > 0) {
      baseline = earlier[earlier.length - 1].equity;
    }
  }

  if (baseline === null || baseline <= 0) {
    return null;
  }

  const pct = ((current - baseline) / baseline) * 100;
  const direction: DailyChange["direction"] =
    pct > 0.005 ? "up" : pct < -0.005 ? "down" : "flat";
  return { pct, direction };
}
