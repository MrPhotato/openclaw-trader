import type { Ref } from "react";
import { Bar, CartesianGrid, ComposedChart, Customized, Line, Tooltip, XAxis, YAxis } from "recharts";

import {
  balanceAxisTickLabel,
  balanceWindowLabel,
  trimNumber,
  type BalanceGranularity,
  type BalancePoint,
} from "../../lib/format";
import { ChartShell } from "../primitives/ChartShell";
import {
  CHART_TOOLTIP_CONTENT_STYLE,
  CHART_TOOLTIP_ITEM_STYLE,
  CHART_TOOLTIP_LABEL_STYLE,
  CHART_TOOLTIP_WRAPPER_STYLE,
} from "./chartConstants";
import { useScrollPinnedChart } from "./useScrollPinnedChart";

function FixedBalanceAxis(props: { ticks: number[] }) {
  const labels = props.ticks.length > 0 ? [...props.ticks].reverse() : [0];

  return (
    <div
      data-testid="balance-chart-fixed-axis"
      className="grid h-[260px] grid-rows-[1fr_32px] border-r border-white/10 pr-2 sm:pr-3"
    >
      <div
        className={`flex min-h-0 flex-col text-right text-[10px] tabular-nums text-slate-500 sm:text-xs ${
          labels.length > 1 ? "justify-between" : "justify-center"
        }`}
      >
        {labels.map((value, index) => (
          <div key={`${value}-${index}`}>{balanceAxisTickLabel(value)}</div>
        ))}
      </div>
      <div data-testid="balance-chart-fixed-axis-footer" aria-hidden="true" />
    </div>
  );
}

export type BalanceTradeMarker = {
  key: string;
  label: string; // x-axis label (bucket label) the marker snaps to
  equity: number; // y value on the equity curve at that bucket
  direction: "buy" | "sell";
  coin: string;
};

/**
 * Pin-style trade badge: rounded top with a downward tail that touches
 * the price point. `B` for buy (green) / `S` for sell (red).
 * Coin label sits beneath the tail tip so both BTC and ETH trades can
 * coexist on the equity line without visual confusion.
 */
function TradeMarkerShape(props: { cx?: number; cy?: number; direction: "buy" | "sell"; coin: string }) {
  const { cx, cy, direction, coin } = props;
  if (cx === undefined || cy === undefined || !Number.isFinite(cx) || !Number.isFinite(cy)) return null;
  const fill = direction === "buy" ? "#22c55e" : "#ef4444";
  const stroke = direction === "buy" ? "#14532d" : "#7f1d1d";
  const letter = direction === "buy" ? "B" : "S";
  // Pin footprint: rounded rectangle (width 16, height 14) above the
  // data point, then a small triangular tail pointing down into it.
  // Coordinates are anchored so the tail tip sits at (cx, cy).
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
      <text
        x={cx}
        y={cy + 13}
        textAnchor="middle"
        fontSize={9}
        fill="#cbd5e1"
        opacity={0.8}
      >
        {coin}
      </text>
    </g>
  );
}

export function BalanceChart(props: {
  series: BalancePoint[];
  ticks: number[];
  domain: number[];
  chartWidth: number;
  granularity: BalanceGranularity;
  tradeMarkers?: BalanceTradeMarker[];
  /** When provided, uses the parent-supplied ref instead of managing its own — lets the parent sync scroll across multiple charts. */
  scrollViewportRef?: Ref<HTMLDivElement>;
}) {
  const internalRef = useScrollPinnedChart<HTMLDivElement>({
    pinDeps: [props.granularity, props.series.length, props.chartWidth],
    wheelHijack: {
      active: props.series.length > 1,
      deps: [props.series.length],
    },
  });
  // Prefer the external ref when the parent wants to control scrolling (sync mode).
  const viewportRef = props.scrollViewportRef ?? internalRef;

  const markers = props.tradeMarkers ?? [];

  return (
    <ChartShell>
      <div className="grid min-w-0 grid-cols-[56px,minmax(0,1fr)] gap-2 sm:grid-cols-[72px,minmax(0,1fr)] sm:gap-3">
        <FixedBalanceAxis ticks={props.ticks} />
        <div
          ref={viewportRef}
          data-testid="balance-chart-viewport"
          className="w-full max-w-full overflow-x-auto overflow-y-hidden"
          style={{ touchAction: "pan-x", overscrollBehaviorX: "contain", overscrollBehaviorY: "contain" }}
        >
          <div style={{ width: `${props.chartWidth}px`, minWidth: "100%" }}>
            {/*
              ComposedChart (not LineChart) + an invisible Bar forces the
              internal XAxis scale to scaleBand with the SAME bandwidth
              Recharts uses on the K-line below — that way every bucket
              index maps to the exact same pixel on both charts, and
              mirroring scrollLeft yields pixel-perfect time alignment.
            */}
            <ComposedChart
              width={props.chartWidth}
              height={260}
              data={props.series}
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
              <YAxis hide domain={props.domain} ticks={props.ticks} />
              <Tooltip
                cursor={{ stroke: "rgba(113,246,209,0.35)" }}
                formatter={(value: number) => [`$${trimNumber(value)}`, balanceWindowLabel(props.granularity)]}
                labelFormatter={(label) => `时间：${label}`}
                contentStyle={CHART_TOOLTIP_CONTENT_STYLE}
                itemStyle={CHART_TOOLTIP_ITEM_STYLE}
                labelStyle={CHART_TOOLTIP_LABEL_STYLE}
                wrapperStyle={CHART_TOOLTIP_WRAPPER_STYLE}
              />
              {/* Hidden Bar — exists only to force scaleBand alignment. */}
              <Bar dataKey="equity" fill="transparent" barSize={0} isAnimationActive={false} legendType="none" />
              <Line
                type="monotone"
                dataKey="equity"
                stroke="#71f6d1"
                strokeWidth={3}
                dot={false}
                connectNulls
                activeDot={{ r: 4 }}
                isAnimationActive={false}
              />
              <Customized
                component={(chartCtx: unknown) => {
                  const ctx = chartCtx as {
                    xAxisMap?: Record<string, {
                      scale: ((value: unknown) => number) & { bandwidth?: () => number };
                      categoricalDomain?: string[];
                    }>;
                    yAxisMap?: Record<string, { scale: (value: number) => number }>;
                  };
                  const xAxis = ctx.xAxisMap ? Object.values(ctx.xAxisMap)[0] : undefined;
                  const yAxis = ctx.yAxisMap ? Object.values(ctx.yAxisMap)[0] : undefined;
                  if (!xAxis || !yAxis) return null;
                  const categorical = xAxis.categoricalDomain ?? [];
                  const labelToIndex = new Map<string, number>();
                  props.series.forEach((point, i) => labelToIndex.set(point.label, i));
                  return (
                    <g>
                      {markers.map((marker) => {
                        const categoricalIdx = categorical.indexOf(marker.label);
                        const idx = categoricalIdx >= 0 ? categoricalIdx : labelToIndex.get(marker.label) ?? -1;
                        if (idx < 0) return null;
                        const rawX = xAxis.scale(idx);
                        const y = yAxis.scale(marker.equity);
                        if (!Number.isFinite(rawX) || !Number.isFinite(y)) return null;
                        const bandwidth =
                          typeof xAxis.scale.bandwidth === "function" ? xAxis.scale.bandwidth() : 0;
                        const cx = rawX + bandwidth / 2;
                        return (
                          <TradeMarkerShape
                            key={marker.key}
                            cx={cx}
                            cy={y}
                            direction={marker.direction}
                            coin={marker.coin}
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
