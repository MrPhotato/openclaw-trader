import { toNumber } from "./misc";

export type KlineTimeframe = "15m" | "1h" | "4h" | "1d";

export const KLINE_TIMEFRAME_TO_BACKEND: Record<KlineTimeframe, string> = {
  "15m": "15m",
  "1h": "1h",
  "4h": "4h",
  "1d": "24h",
};

export const KLINE_TIMEFRAME_LABEL: Record<KlineTimeframe, string> = {
  "15m": "15 分钟",
  "1h": "1 小时",
  "4h": "4 小时",
  "1d": "日线",
};

export type CandlePoint = {
  timestamp: number;
  label: string;
  open: number;
  high: number;
  low: number;
  close: number;
  body: [number, number];
  wick: [number, number];
  isUp: boolean;
};

export function buildCandlePoints(
  points: Array<{
    timestamp: number;
    close: string;
    open?: string | null;
    high?: string | null;
    low?: string | null;
  }>,
  timeframe: KlineTimeframe,
): CandlePoint[] {
  return points
    .map((raw) => {
      const close = toNumber(raw.close);
      if (close === null) {
        return null;
      }
      const open = toNumber(raw.open) ?? close;
      const high = toNumber(raw.high) ?? Math.max(open, close);
      const low = toNumber(raw.low) ?? Math.min(open, close);
      const timestampMs = raw.timestamp * 1000;
      return {
        timestamp: timestampMs,
        label: formatCandleLabel(timestampMs, timeframe),
        open,
        high,
        low,
        close,
        body: [Math.min(open, close), Math.max(open, close)] as [number, number],
        wick: [low, high] as [number, number],
        isUp: close >= open,
      };
    })
    .filter((candle): candle is CandlePoint => candle !== null)
    .sort((a, b) => a.timestamp - b.timestamp);
}

export function formatCandleLabel(timestampMs: number, timeframe: KlineTimeframe): string {
  const date = new Date(timestampMs);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  if (timeframe === "1d") {
    return date.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit" });
  }
  if (timeframe === "4h") {
    return date.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      hour12: false,
    });
  }
  return date.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function computeKlineChartWidth(length: number): number {
  const minWidth = 520;
  const pointWidth = 16;
  return Math.max(minWidth, length * pointWidth);
}

export function buildKlinePriceDomain(candles: CandlePoint[]): [number, number] | [] {
  if (candles.length === 0) {
    return [];
  }
  let min = candles[0].low;
  let max = candles[0].high;
  for (const candle of candles) {
    if (candle.low < min) {
      min = candle.low;
    }
    if (candle.high > max) {
      max = candle.high;
    }
  }
  if (min === max) {
    const pad = Math.abs(min) * 0.01 || 1;
    return [min - pad, max + pad];
  }
  const pad = (max - min) * 0.08;
  return [min - pad, max + pad];
}

export function buildKlinePriceTicks(domain: [number, number] | []): number[] {
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

/**
 * Re-bucket candles onto an external time grid (typically the balance
 * chart's bucketed series) so that two side-by-side charts render on a
 * PIXEL-IDENTICAL X axis. The output has one slot per grid entry:
 *
 *   - the candle whose raw timestamp falls inside that bucket, or
 *   - a "phantom" entry with NaN OHLC — Recharts skips drawing anything
 *     for NaN values, which leaves the slot empty without breaking the
 *     shared category axis.
 *
 * Labels are taken from the grid (not the candle's own label) so
 * XAxis / Tooltip / ReferenceLine are interchangeable across charts.
 */
export function alignCandlesToBucketGrid(
  candles: CandlePoint[],
  grid: Array<{ label: string; createdAtMs: number }>,
  bucketMs: number,
): CandlePoint[] {
  if (grid.length === 0) return [];
  const sorted = [...candles].sort((a, b) => a.timestamp - b.timestamp);
  const aligned: CandlePoint[] = [];
  let idx = 0;
  for (const slot of grid) {
    const bucketStart = slot.createdAtMs;
    const bucketEnd = bucketStart + bucketMs;
    while (idx < sorted.length && sorted[idx].timestamp < bucketStart) idx++;
    let hit: CandlePoint | null = null;
    while (idx < sorted.length && sorted[idx].timestamp < bucketEnd) {
      hit = sorted[idx];
      idx++;
    }
    if (hit) {
      aligned.push({ ...hit, label: slot.label, timestamp: bucketStart });
    } else {
      aligned.push({
        timestamp: bucketStart,
        label: slot.label,
        open: Number.NaN,
        high: Number.NaN,
        low: Number.NaN,
        close: Number.NaN,
        body: [Number.NaN, Number.NaN],
        wick: [Number.NaN, Number.NaN],
        isUp: false,
      });
    }
  }
  return aligned;
}
