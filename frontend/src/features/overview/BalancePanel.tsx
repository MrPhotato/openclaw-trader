import { useMemo, useState } from "react";

import type { AssetRecord, MarketContextData, OverviewData } from "../../lib/types";
import {
  balanceScrollCaption,
  buildBalanceDomain,
  buildBalanceHistory,
  buildBalanceTicks,
  buildCandlePoints,
  buildKlinePriceDomain,
  buildKlinePriceTicks,
  buildNominalExposurePills,
  classifyTradeDirection,
  computeBalanceChartWidth,
  computeDailyChange,
  computeKlineChartWidth,
  configuredLeverageLabel,
  extractTradeTimeMs,
  firstFill,
  snapTimestampToBucketLabel,
  trimNumber,
  usdCompactText,
  type BalanceGranularity,
  type CandlePoint,
  type DailyChange,
  type KlineTimeframe,
} from "../../lib/format";
import { Panel } from "../../components/primitives/Panel";
import { SummaryPill } from "../../components/primitives/Metrics";
import { BalanceChart, type BalanceTradeMarker } from "../../components/charts/BalanceChart";
import { KlineChart, type KlineTradeMarker } from "../../components/charts/KlineChart";
import { EmptyState } from "../../components/primitives/EmptyState";
import { useSyncedScrollPinnedCharts } from "../../components/charts/useSyncedScrollPinnedCharts";
import { CoinExposurePill } from "./CoinExposurePill";
import { RiskThresholdPills } from "./RiskThresholdPills";

const GRANULARITY_OPTIONS: Array<[BalanceGranularity, string]> = [
  ["15m", "15 分钟"],
  ["1h", "1 小时"],
  ["1d", "日线"],
];

// Balance-chart granularity maps 1:1 to a K-line timeframe — we drop the
// orphan "4h" option so both charts always share a single time axis.
const GRANULARITY_TO_KLINE_TIMEFRAME: Record<BalanceGranularity, KlineTimeframe> = {
  "15m": "15m",
  "1h": "1h",
  "1d": "1d",
};
const GRANULARITY_TO_KLINE_BACKEND: Record<BalanceGranularity, string> = {
  "15m": "15m",
  "1h": "1h",
  "1d": "24h",
};

function snapCandleLabel(tsMs: number, candles: CandlePoint[]): string | null {
  if (candles.length === 0) return null;
  const bucketMs = candles.length >= 2 ? Math.abs(candles[1].timestamp - candles[0].timestamp) : 60 * 60 * 1000;
  let nearest = candles[0];
  let bestDelta = Math.abs(candles[0].timestamp - tsMs);
  for (const candle of candles) {
    const delta = Math.abs(candle.timestamp - tsMs);
    if (delta < bestDelta) {
      bestDelta = delta;
      nearest = candle;
    }
  }
  // Only keep markers within ~1 bucket of a candle so we don't pin labels
  // that fall outside the chart's visible window.
  return bestDelta <= bucketMs * 1.5 ? nearest.label : null;
}

function DailyChangeChip(props: { label: string; change: DailyChange | null }) {
  if (props.change === null) return null;
  const tone =
    props.change.direction === "up"
      ? "text-emerald-300"
      : props.change.direction === "down"
        ? "text-rose-300"
        : "text-slate-400";
  const marker = props.change.direction === "up" ? "▲" : props.change.direction === "down" ? "▼" : "■";
  const sign = props.change.direction === "up" ? "+" : "";
  return (
    <span
      className={`inline-flex items-center gap-1 text-[11px] font-medium tabular-nums ${tone}`}
      aria-label={`${props.label}当日涨跌`}
    >
      <span className="text-[9px] uppercase tracking-[0.18em] text-slate-500">{props.label}</span>
      {marker} {sign}
      {props.change.pct.toFixed(2)}%
    </span>
  );
}

export function BalancePanel(props: {
  overview?: OverviewData;
  latestPortfolio: Record<string, unknown>;
  latestStrategy: Record<string, unknown>;
  granularity: BalanceGranularity;
  onGranularityChange: (value: BalanceGranularity) => void;
  executionRecords: AssetRecord[];
  marketContext?: MarketContextData;
}) {
  const { overview, latestPortfolio, latestStrategy, granularity, executionRecords, marketContext } = props;

  const supportedCoins = (overview?.system as { supported_coins?: readonly string[] } | undefined)?.supported_coins;

  const series = useMemo(
    () => buildBalanceHistory(overview?.portfolio_history ?? [], latestPortfolio, granularity),
    [overview?.portfolio_history, latestPortfolio, granularity],
  );
  const ticks = useMemo(() => buildBalanceTicks(series), [series]);
  const domain = useMemo(() => buildBalanceDomain(series), [series]);
  const balanceChartWidth = useMemo(
    () => computeBalanceChartWidth(series.length, granularity),
    [series.length, granularity],
  );
  const exposurePills = useMemo(
    () => buildNominalExposurePills(latestPortfolio, latestStrategy, supportedCoins),
    [latestPortfolio, latestStrategy, supportedCoins],
  );
  const dailyChangeUtc = useMemo(
    () => computeDailyChange(latestPortfolio["total_equity_usd"], overview?.portfolio_history ?? []),
    [latestPortfolio, overview?.portfolio_history],
  );
  const dailyChangeBeijing = useMemo(
    () =>
      computeDailyChange(
        latestPortfolio["total_equity_usd"],
        overview?.portfolio_history ?? [],
        { offsetHours: 8 },
      ),
    [latestPortfolio, overview?.portfolio_history],
  );

  const contexts = marketContext?.market_context ?? {};
  const availableCoins = Object.keys(contexts);
  const [coinOverride, setCoinOverride] = useState<string>("");
  const activeCoin = coinOverride && contexts[coinOverride] ? coinOverride : availableCoins[0] ?? "";
  const contextForCoin = activeCoin ? contexts[activeCoin] : undefined;
  const backendKey = GRANULARITY_TO_KLINE_BACKEND[granularity];
  const klineTimeframe = GRANULARITY_TO_KLINE_TIMEFRAME[granularity];
  const klineSeries = contextForCoin?.compressed_price_series?.[backendKey];
  const candles = useMemo(
    () => buildCandlePoints(klineSeries?.points ?? [], klineTimeframe),
    [klineSeries, klineTimeframe],
  );
  const klineChartWidth = useMemo(() => computeKlineChartWidth(candles.length), [candles.length]);
  const priceDomain = useMemo(() => buildKlinePriceDomain(candles), [candles]);
  const priceTicks = useMemo(() => buildKlinePriceTicks(priceDomain), [priceDomain]);
  const lastCandle = candles.length > 0 ? candles[candles.length - 1] : null;
  const firstCandle = candles.length > 0 ? candles[0] : null;
  const candleChangePct =
    firstCandle && lastCandle && firstCandle.open !== 0
      ? ((lastCandle.close - firstCandle.open) / firstCandle.open) * 100
      : null;

  const balanceMarkers = useMemo<BalanceTradeMarker[]>(() => {
    if (series.length === 0) return [];
    return executionRecords
      .map((record, idx) => {
        const direction = classifyTradeDirection(record);
        if (direction === null) return null;
        const ts = extractTradeTimeMs(record);
        if (ts === null) return null;
        const label = snapTimestampToBucketLabel(ts, series, granularity);
        if (label === null) return null;
        const bucket = series.find((p) => p.label === label);
        if (!bucket) return null;
        const coin = String(record.payload["coin"] ?? record.payload["symbol"] ?? "").toUpperCase() || "?";
        return {
          key: `${record.asset_id ?? idx}-balance`,
          label,
          equity: bucket.equity,
          direction,
          coin,
        };
      })
      .filter((m): m is BalanceTradeMarker => m !== null);
  }, [executionRecords, series, granularity]);

  const klineMarkers = useMemo<KlineTradeMarker[]>(() => {
    if (candles.length === 0 || !activeCoin) return [];
    return executionRecords
      .map((record, idx) => {
        const coin = String(record.payload["coin"] ?? record.payload["symbol"] ?? "").toUpperCase();
        if (coin !== activeCoin.toUpperCase()) return null;
        const direction = classifyTradeDirection(record);
        if (direction === null) return null;
        const ts = extractTradeTimeMs(record);
        if (ts === null) return null;
        const label = snapCandleLabel(ts, candles);
        if (label === null) return null;
        const price = firstFill(record)?.price ?? null;
        if (price === null) return null;
        return {
          key: `${record.asset_id ?? idx}-kline`,
          label,
          price,
          direction,
        };
      })
      .filter((m): m is KlineTradeMarker => m !== null);
  }, [executionRecords, candles, activeCoin]);

  // Shared scroll + wheel-hijack + pin-to-right across both chart viewports.
  const { balanceRef, klineRef } = useSyncedScrollPinnedCharts({
    pinDeps: [granularity, series.length, balanceChartWidth, activeCoin, candles.length, klineChartWidth],
    wheelHijack: {
      active: series.length > 1 || candles.length > 1,
      deps: [series.length, candles.length],
    },
  });

  return (
    <Panel title="账户余额轨迹" eyebrow="Equity & Market" variant="hero">
      <div className="mb-3 grid gap-2 sm:grid-cols-2">
        <div className="rounded-2xl border border-white/10 bg-white/[0.04] px-3 py-2 ring-hairline">
          <div className="text-[10px] uppercase tracking-[0.22em] text-slate-500">账户余额（当前总权益）</div>
          <div className="mt-0.5 flex flex-wrap items-baseline gap-x-3">
            <span className="text-base font-semibold tabular-nums leading-tight text-slate-100 sm:text-lg">
              {usdCompactText(latestPortfolio["total_equity_usd"])}
            </span>
            <DailyChangeChip label="UTC" change={dailyChangeUtc} />
            <DailyChangeChip label="BJT" change={dailyChangeBeijing} />
          </div>
        </div>
        <SummaryPill label="当前杠杆" value={configuredLeverageLabel(latestPortfolio)} />
      </div>
      <div className="mb-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {exposurePills.map((item) => (
          <CoinExposurePill
            key={item.coin}
            coin={item.coin}
            direction={item.direction}
            directionTone={item.directionTone}
            exposure={item.exposure}
            strategyExposure={item.strategyExposure}
            share={item.share}
            strategyShare={item.strategyShare}
          />
        ))}
      </div>
      {/* Row 1 above the charts: portfolio risk threshold ladder. */}
      <div className="mb-2">
        <RiskThresholdPills riskOverlay={overview?.risk_overlay} />
      </div>
      {/* Row 2 above the charts: shared granularity toggle + K-line coin switch. */}
      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
        <div className="flex flex-wrap gap-2" data-testid="kline-timeframe-tabs">
          {GRANULARITY_OPTIONS.map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => props.onGranularityChange(key)}
              className={`rounded-full px-3 py-1.5 text-xs transition ${
                granularity === key
                  ? "bg-neon/90 text-ink shadow-[0_0_14px_rgba(113,246,209,0.4)]"
                  : "border border-white/10 bg-white/5 text-slate-300 hover:border-neon/30 hover:bg-white/10 hover:text-white"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2" data-testid="kline-coin-tabs">
          {availableCoins.length === 0 ? (
            <span className="text-[11px] text-slate-500">K 线币种待数据</span>
          ) : (
            availableCoins.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setCoinOverride(option)}
                className={`rounded-full px-3 py-1.5 text-xs transition ${
                  option === activeCoin
                    ? "bg-ember/90 text-ink shadow-[0_0_12px_rgba(255,125,69,0.45)]"
                    : "border border-white/10 bg-white/5 text-slate-300 hover:border-ember/40 hover:bg-white/10 hover:text-white"
                }`}
              >
                {option}
              </button>
            ))
          )}
        </div>
      </div>

      {/* Balance chart — shows BTC+ETH trade markers regardless of the K-line coin. */}
      <BalanceChart
        series={series}
        ticks={ticks}
        domain={domain}
        chartWidth={balanceChartWidth}
        granularity={granularity}
        tradeMarkers={balanceMarkers}
        scrollViewportRef={balanceRef}
      />

      {/* K-line sub-header: ties the active coin + last price to the chart below. */}
      <div className="mt-4 mb-2 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm text-slate-300">
        <span className="text-[10px] uppercase tracking-[0.22em] text-slate-500">行情 K 线</span>
        {activeCoin ? <span className="text-base font-semibold text-slate-100">{activeCoin}</span> : null}
        {lastCandle ? (
          <span className="text-slate-200 tabular-nums">最新 ${trimNumber(lastCandle.close)}</span>
        ) : null}
        {candleChangePct !== null ? (
          <span className={`tabular-nums ${candleChangePct >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
            {candleChangePct >= 0 ? "+" : ""}
            {candleChangePct.toFixed(2)}%
          </span>
        ) : null}
        {klineSeries?.window ? <span className="text-slate-500">窗口 {klineSeries.window}</span> : null}
      </div>

      {candles.length === 0 ? (
        <EmptyState
          message={
            availableCoins.length === 0
              ? "还没有拿到行情序列，等待下一轮市场数据采集。"
              : "此周期暂无行情采样点。"
          }
        />
      ) : (
        <KlineChart
          candles={candles}
          chartWidth={klineChartWidth}
          priceDomain={priceDomain}
          priceTicks={priceTicks}
          tradeMarkers={klineMarkers}
          scrollViewportRef={klineRef}
        />
      )}

      <div className="mt-3 text-[11px] leading-5 text-slate-500 sm:text-xs" data-testid="balance-viewport-caption">
        {balanceScrollCaption(series.length, granularity)}
      </div>
    </Panel>
  );
}
