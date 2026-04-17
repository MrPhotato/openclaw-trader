import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";

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

export function BalanceChart(props: {
  series: BalancePoint[];
  ticks: number[];
  domain: number[];
  chartWidth: number;
  granularity: BalanceGranularity;
}) {
  const viewportRef = useScrollPinnedChart<HTMLDivElement>({
    pinDeps: [props.granularity, props.series.length, props.chartWidth],
    wheelHijack: {
      active: props.series.length > 1,
      deps: [props.series.length],
    },
  });

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
            <LineChart
              width={props.chartWidth}
              height={260}
              data={props.series}
              margin={{ top: 12, right: 8, bottom: 0, left: 0 }}
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
              <Line
                type="monotone"
                dataKey="equity"
                stroke="#71f6d1"
                strokeWidth={3}
                dot={false}
                connectNulls
                activeDot={{ r: 4 }}
              />
            </LineChart>
          </div>
        </div>
      </div>
    </ChartShell>
  );
}
