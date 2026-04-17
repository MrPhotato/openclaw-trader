import type { Ref } from "react";
import { Bar, CartesianGrid, Cell, ComposedChart, Customized, Tooltip, XAxis, YAxis } from "recharts";

import { trimNumber, type CandlePoint } from "../../lib/format";
import { ChartShell } from "../primitives/ChartShell";
import {
  CHART_TOOLTIP_CONTENT_STYLE,
  CHART_TOOLTIP_ITEM_STYLE,
  CHART_TOOLTIP_LABEL_STYLE,
  CHART_TOOLTIP_WRAPPER_STYLE,
} from "./chartConstants";
import { useScrollPinnedChart } from "./useScrollPinnedChart";

export type KlineTradeMarker = {
  key: string;
  label: string;
  price: number;
  direction: "buy" | "sell";
};

function FixedKlineAxis(props: { ticks: number[] }) {
  const labels = props.ticks.length > 0 ? [...props.ticks].reverse() : [0];
  return (
    <div
      data-testid="kline-chart-fixed-axis"
      className="grid h-[260px] grid-rows-[1fr_32px] border-r border-white/10 pr-2 sm:pr-3"
    >
      <div
        className={`flex min-h-0 flex-col text-right text-[10px] tabular-nums text-slate-500 sm:text-xs ${
          labels.length > 1 ? "justify-between" : "justify-center"
        }`}
      >
        {labels.map((value, index) => (
          <div key={`${value}-${index}`}>${trimNumber(value)}</div>
        ))}
      </div>
      <div aria-hidden="true" />
    </div>
  );
}

function CandleTooltip(props: {
  active?: boolean;
  payload?: Array<{ payload?: CandlePoint }>;
  label?: string;
}) {
  if (!props.active || !props.payload || props.payload.length === 0) {
    return null;
  }
  const candle = props.payload[0]?.payload;
  if (!candle) {
    return null;
  }
  const toneClass = candle.isUp ? "text-emerald-300" : "text-rose-300";
  return (
    <div style={CHART_TOOLTIP_CONTENT_STYLE} className="space-y-1 px-3 py-2 text-xs tabular-nums">
      <div style={CHART_TOOLTIP_LABEL_STYLE}>时间：{candle.label}</div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
        <div>开：${trimNumber(candle.open)}</div>
        <div>高：${trimNumber(candle.high)}</div>
        <div>低：${trimNumber(candle.low)}</div>
        <div className={toneClass}>收：${trimNumber(candle.close)}</div>
      </div>
    </div>
  );
}

/**
 * Pin-style trade badge (see BalanceChart for rationale): rounded top
 * with a downward tail touching the candle's fill price. `B` / `S` in
 * the badge, no coin label (each K-line only shows its own coin's
 * trades, so the coin is implied).
 */
function KlineTradeMarkerShape(props: { cx?: number; cy?: number; direction: "buy" | "sell" }) {
  const { cx, cy, direction } = props;
  if (cx === undefined || cy === undefined) return null;
  const fill = direction === "buy" ? "#22c55e" : "#ef4444";
  const stroke = direction === "buy" ? "#14532d" : "#7f1d1d";
  const letter = direction === "buy" ? "B" : "S";
  const top = cy - 20;
  const bottom = cy - 6;
  const path = [
    `M ${cx - 8} ${top + 3}`,
    `Q ${cx - 8} ${top} ${cx - 5} ${top}`,
    `L ${cx + 5} ${top}`,
    `Q ${cx + 8} ${top} ${cx + 8} ${top + 3}`,
    `L ${cx + 8} ${bottom}`,
    `L ${cx} ${cy}`,
    `L ${cx - 8} ${bottom}`,
    "Z",
  ].join(" ");
  return (
    <g>
      <path d={path} fill={fill} stroke={stroke} strokeWidth={0.8} opacity={0.95} />
      <text
        x={cx}
        y={cy - 10}
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize={9}
        fontWeight={700}
        fill="#fff"
      >
        {letter}
      </text>
    </g>
  );
}

/**
 * Candle chart body — no internal state, no surrounding Panel. The parent
 * owns the coin / timeframe / width so it can keep this chart in lockstep
 * with the balance chart above it (same data key, same physical width, same
 * scroll container size).
 */
export function KlineChart(props: {
  candles: CandlePoint[];
  chartWidth: number;
  priceDomain: [number, number] | [];
  priceTicks: number[];
  /** Parent-managed scroll ref when syncing with another chart. */
  scrollViewportRef?: Ref<HTMLDivElement>;
  tradeMarkers?: KlineTradeMarker[];
}) {
  const internalRef = useScrollPinnedChart<HTMLDivElement>({
    pinDeps: [props.candles.length, props.chartWidth],
  });
  const viewportRef = props.scrollViewportRef ?? internalRef;
  const markers = props.tradeMarkers ?? [];

  return (
    <ChartShell>
      <div className="grid min-w-0 grid-cols-[56px,minmax(0,1fr)] gap-2 sm:grid-cols-[72px,minmax(0,1fr)] sm:gap-3">
        <FixedKlineAxis ticks={props.priceTicks} />
        <div
          ref={viewportRef}
          data-testid="kline-chart-viewport"
          className="w-full max-w-full overflow-x-auto overflow-y-hidden"
          style={{ touchAction: "pan-x", overscrollBehaviorX: "contain", overscrollBehaviorY: "contain" }}
        >
          <div style={{ width: `${props.chartWidth}px`, minWidth: "100%" }}>
            <ComposedChart
              width={props.chartWidth}
              height={260}
              data={props.candles}
              margin={{ top: 12, right: 8, bottom: 0, left: 0 }}
              barCategoryGap={2}
            >
              <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
              <XAxis
                dataKey="label"
                tick={{ fill: "#9fb0c7", fontSize: 12 }}
                axisLine={false}
                tickLine={false}
                interval="preserveStartEnd"
                minTickGap={28}
                height={32}
              />
              <YAxis hide domain={props.priceDomain} ticks={props.priceTicks} />
              <Tooltip
                cursor={{ stroke: "rgba(113,246,209,0.35)" }}
                content={<CandleTooltip />}
                contentStyle={CHART_TOOLTIP_CONTENT_STYLE}
                itemStyle={CHART_TOOLTIP_ITEM_STYLE}
                labelStyle={CHART_TOOLTIP_LABEL_STYLE}
                wrapperStyle={CHART_TOOLTIP_WRAPPER_STYLE}
              />
              <Bar dataKey="wick" barSize={1} isAnimationActive={false}>
                {props.candles.map((candle, index) => (
                  <Cell key={`wick-${index}`} fill={candle.isUp ? "#34d399" : "#f87171"} />
                ))}
              </Bar>
              <Bar dataKey="body" barSize={10} isAnimationActive={false}>
                {props.candles.map((candle, index) => (
                  <Cell key={`body-${index}`} fill={candle.isUp ? "#34d399" : "#f87171"} />
                ))}
              </Bar>
              <Customized
                component={(chartCtx: unknown) => {
                  // Recharts' ComposedChart-with-Bar uses a numeric-index scale
                  // for the category X axis — calling scale("11:00") returns
                  // NaN. Falls back to scaling the candle's own index in the
                  // rendered data if categoricalDomain isn't exposed.
                  const ctx = chartCtx as {
                    xAxisMap?: Record<string, {
                      scale: ((value: unknown) => number) & { bandwidth?: () => number };
                      categoricalDomain?: string[];
                    }>;
                    yAxisMap?: Record<string, { scale: (value: number) => number }>;
                  };
                  if (typeof window !== "undefined") {
                    (window as { __rechartsCtx?: unknown }).__rechartsCtx = ctx;
                  }
                  const xAxis = ctx.xAxisMap ? Object.values(ctx.xAxisMap)[0] : undefined;
                  const yAxis = ctx.yAxisMap ? Object.values(ctx.yAxisMap)[0] : undefined;
                  if (!xAxis || !yAxis) return null;
                  const categorical = xAxis.categoricalDomain ?? [];
                  // Build a lookup for candle-label → candle-index (0..N-1)
                  // as a fallback when categoricalDomain is empty.
                  const labelToIndex = new Map<string, number>();
                  props.candles.forEach((candle, i) => labelToIndex.set(candle.label, i));
                  return (
                    <g>
                      {markers.map((marker) => {
                        const categoricalIdx = categorical.indexOf(marker.label);
                        const idx = categoricalIdx >= 0 ? categoricalIdx : labelToIndex.get(marker.label) ?? -1;
                        if (idx < 0) return null;
                        const rawX = xAxis.scale(idx);
                        const y = yAxis.scale(marker.price);
                        if (!Number.isFinite(rawX) || !Number.isFinite(y)) return null;
                        const bandwidth =
                          typeof xAxis.scale.bandwidth === "function" ? xAxis.scale.bandwidth() : 0;
                        const cx = rawX + bandwidth / 2;
                        return (
                          <KlineTradeMarkerShape
                            key={marker.key}
                            cx={cx}
                            cy={y}
                            direction={marker.direction}
                          />
                        );
                      })}
                    </g>
                  );
                }}
              />
            </ComposedChart>
          </div>
        </div>
      </div>
    </ChartShell>
  );
}
