import { useMemo } from "react";

import type { OverviewData } from "../../lib/types";
import {
  balanceScrollCaption,
  buildBalanceDomain,
  buildBalanceHistory,
  buildBalanceTicks,
  buildNominalExposurePills,
  computeBalanceChartWidth,
  configuredLeverageLabel,
  usdCompactText,
  type BalanceGranularity,
} from "../../lib/format";
import { Panel } from "../../components/primitives/Panel";
import { SummaryPill } from "../../components/primitives/Metrics";
import { BalanceChart } from "../../components/charts/BalanceChart";
import { CoinExposurePill } from "./CoinExposurePill";
import { RiskThresholdPills } from "./RiskThresholdPills";

const GRANULARITY_OPTIONS: Array<[BalanceGranularity, string]> = [
  ["15m", "15 分钟"],
  ["1h", "1 小时"],
  ["1d", "日线"],
];

export function BalancePanel(props: {
  overview?: OverviewData;
  latestPortfolio: Record<string, unknown>;
  latestStrategy: Record<string, unknown>;
  granularity: BalanceGranularity;
  onGranularityChange: (value: BalanceGranularity) => void;
}) {
  const { overview, latestPortfolio, latestStrategy, granularity } = props;

  const series = useMemo(
    () => buildBalanceHistory(overview?.portfolio_history ?? [], latestPortfolio, granularity),
    [overview?.portfolio_history, latestPortfolio, granularity],
  );
  const ticks = useMemo(() => buildBalanceTicks(series), [series]);
  const domain = useMemo(() => buildBalanceDomain(series), [series]);
  const chartWidth = useMemo(() => computeBalanceChartWidth(series.length, granularity), [series.length, granularity]);
  const exposurePills = useMemo(
    () =>
      buildNominalExposurePills(
        latestPortfolio,
        latestStrategy,
        (overview?.system as { supported_coins?: readonly string[] } | undefined)?.supported_coins,
      ),
    [latestPortfolio, latestStrategy, overview?.system],
  );

  return (
    <Panel title="账户余额轨迹" eyebrow="Equity Track" variant="hero">
      <div className="mb-3 grid gap-2 sm:grid-cols-2">
        <SummaryPill label="账户余额（当前总权益）" value={usdCompactText(latestPortfolio["total_equity_usd"])} />
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
      <BalanceChart series={series} ticks={ticks} domain={domain} chartWidth={chartWidth} granularity={granularity} />
      <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
        <div className="flex flex-wrap gap-2">
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
        <div className="text-[11px] leading-5 text-slate-500 sm:text-xs" data-testid="balance-viewport-caption">
          {balanceScrollCaption(series.length, granularity)}
        </div>
      </div>
      <div className="mt-3">
        <RiskThresholdPills riskOverlay={overview?.risk_overlay} />
      </div>
    </Panel>
  );
}
