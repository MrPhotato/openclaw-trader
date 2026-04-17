import { useState } from "react";
import { Bar, CartesianGrid, Cell, ComposedChart, Tooltip, XAxis, YAxis } from "recharts";

import type { MarketContextData } from "../../lib/types";
import {
  buildCandlePoints,
  buildKlinePriceDomain,
  buildKlinePriceTicks,
  computeKlineChartWidth,
  KLINE_TIMEFRAME_LABEL,
  KLINE_TIMEFRAME_TO_BACKEND,
  trimNumber,
  type CandlePoint,
  type KlineTimeframe,
} from "../../lib/format";
import { ChartShell } from "../primitives/ChartShell";
import { EmptyState } from "../primitives/EmptyState";
import { Panel } from "../primitives/Panel";
import {
  CHART_TOOLTIP_CONTENT_STYLE,
  CHART_TOOLTIP_ITEM_STYLE,
  CHART_TOOLTIP_LABEL_STYLE,
  CHART_TOOLTIP_WRAPPER_STYLE,
} from "./chartConstants";
import { useScrollPinnedChart } from "./useScrollPinnedChart";

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

export function KlineChart(props: { marketContext?: MarketContextData }) {
  const contexts = props.marketContext?.market_context ?? {};
  const availableCoins = Object.keys(contexts);
  const [coin, setCoin] = useState<string>("");
  const [timeframe, setTimeframe] = useState<KlineTimeframe>("1h");

  const activeCoin = coin && contexts[coin] ? coin : availableCoins[0] ?? "";
  const contextForCoin = activeCoin ? contexts[activeCoin] : undefined;
  const backendKey = KLINE_TIMEFRAME_TO_BACKEND[timeframe];
  const series = contextForCoin?.compressed_price_series?.[backendKey];
  const candles = buildCandlePoints(series?.points ?? [], timeframe);
  const chartWidth = computeKlineChartWidth(candles.length);
  const priceDomain = buildKlinePriceDomain(candles);
  const priceTicks = buildKlinePriceTicks(priceDomain);
  const lastCandle = candles.length > 0 ? candles[candles.length - 1] : null;
  const firstCandle = candles.length > 0 ? candles[0] : null;
  const changePct =
    firstCandle && lastCandle && firstCandle.open !== 0
      ? ((lastCandle.close - firstCandle.open) / firstCandle.open) * 100
      : null;

  const viewportRef = useScrollPinnedChart<HTMLDivElement>({
    pinDeps: [activeCoin, timeframe, candles.length, chartWidth],
  });

  if (availableCoins.length === 0) {
    return (
      <Panel title="行情 K 线">
        <EmptyState message="还没有拿到行情序列，等待下一轮市场数据采集。" />
      </Panel>
    );
  }

  return (
    <Panel title="行情 K 线" eyebrow="Market">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2" data-testid="kline-coin-tabs">
          {availableCoins.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setCoin(option)}
              className={`rounded-full px-3 py-1.5 text-xs transition ${
                option === activeCoin
                  ? "bg-neon/90 text-ink shadow-[0_0_12px_rgba(113,246,209,0.35)]"
                  : "border border-white/10 bg-white/5 text-slate-300 hover:border-neon/30 hover:bg-white/10 hover:text-white"
              }`}
            >
              {option}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2" data-testid="kline-timeframe-tabs">
          {(Object.keys(KLINE_TIMEFRAME_LABEL) as KlineTimeframe[]).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => setTimeframe(key)}
              className={`rounded-full px-3 py-1.5 text-xs transition ${
                timeframe === key
                  ? "bg-neon/90 text-ink shadow-[0_0_12px_rgba(113,246,209,0.35)]"
                  : "border border-white/10 bg-white/5 text-slate-300 hover:border-neon/30 hover:bg-white/10 hover:text-white"
              }`}
            >
              {KLINE_TIMEFRAME_LABEL[key]}
            </button>
          ))}
        </div>
      </div>
      <div className="mb-3 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm text-slate-300">
        <span className="text-base font-semibold text-slate-100">{activeCoin}</span>
        {lastCandle ? <span className="text-slate-200 tabular-nums">最新 ${trimNumber(lastCandle.close)}</span> : null}
        {changePct !== null ? (
          <span className={`tabular-nums ${changePct >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
            {changePct >= 0 ? "+" : ""}
            {changePct.toFixed(2)}%
          </span>
        ) : null}
        {series?.window ? <span className="text-slate-500">窗口 {series.window}</span> : null}
      </div>
      <ChartShell>
        {candles.length === 0 ? (
          <EmptyState message="此周期暂无行情采样点。" />
        ) : (
          <div className="grid min-w-0 grid-cols-[56px,minmax(0,1fr)] gap-2 sm:grid-cols-[72px,minmax(0,1fr)] sm:gap-3">
            <FixedKlineAxis ticks={priceTicks} />
            <div
              ref={viewportRef}
              data-testid="kline-chart-viewport"
              className="w-full max-w-full overflow-x-auto overflow-y-hidden"
              style={{ touchAction: "pan-x", overscrollBehaviorX: "contain", overscrollBehaviorY: "contain" }}
            >
              <div style={{ width: `${chartWidth}px`, minWidth: "100%" }}>
                <ComposedChart
                  width={chartWidth}
                  height={260}
                  data={candles}
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
                  <YAxis hide domain={priceDomain} ticks={priceTicks} />
                  <Tooltip
                    cursor={{ stroke: "rgba(113,246,209,0.35)" }}
                    content={<CandleTooltip />}
                    contentStyle={CHART_TOOLTIP_CONTENT_STYLE}
                    itemStyle={CHART_TOOLTIP_ITEM_STYLE}
                    labelStyle={CHART_TOOLTIP_LABEL_STYLE}
                    wrapperStyle={CHART_TOOLTIP_WRAPPER_STYLE}
                  />
                  <Bar dataKey="wick" barSize={1} isAnimationActive={false}>
                    {candles.map((candle, index) => (
                      <Cell key={`wick-${index}`} fill={candle.isUp ? "#34d399" : "#f87171"} />
                    ))}
                  </Bar>
                  <Bar dataKey="body" barSize={10} isAnimationActive={false}>
                    {candles.map((candle, index) => (
                      <Cell key={`body-${index}`} fill={candle.isUp ? "#34d399" : "#f87171"} />
                    ))}
                  </Bar>
                </ComposedChart>
              </div>
            </div>
          </div>
        )}
      </ChartShell>
    </Panel>
  );
}
