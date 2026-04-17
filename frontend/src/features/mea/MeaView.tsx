import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { AgentLatestData, AssetRecord, NewsData } from "../../lib/types";
import { Panel } from "../../components/primitives/Panel";
import { ChartShell } from "../../components/primitives/ChartShell";
import { renderAssetCollection } from "../../components/primitives/Collections";
import { buildImpactBreakdown, nonEmptyText, trimNumber } from "../../lib/format";
import { AgentHero } from "../agents/AgentHero";
import { agentPages } from "../agents/config";
import { MacroEventCard } from "./MacroEventCard";
import {
  CHART_TOOLTIP_CONTENT_STYLE,
  CHART_TOOLTIP_ITEM_STYLE,
  CHART_TOOLTIP_LABEL_STYLE,
  CHART_TOOLTIP_WRAPPER_STYLE,
} from "../../components/charts/chartConstants";

export function MeaView(props: {
  data?: AgentLatestData;
  news?: NewsData;
}) {
  const macroEvents: AssetRecord[] = props.news?.macro_events ?? props.data?.recent_macro_events ?? [];
  const impactBreakdown = buildImpactBreakdown(macroEvents);

  return (
    <section className="space-y-4 sm:space-y-6" data-testid="mea-view">
      <AgentHero agent={agentPages[2]} data={props.data} />
      <section className="grid min-w-0 gap-4 sm:gap-6 lg:grid-cols-[0.92fr_1.08fr]">
        <div className="min-w-0 space-y-4 sm:space-y-6">
          <Panel title="影响分布" eyebrow="Impact">
            <ChartShell>
              <ResponsiveContainer width="100%" height={240}>
                <BarChart data={impactBreakdown}>
                  <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                  <XAxis dataKey="impact" tick={{ fill: "#9fb0c7", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: "#9fb0c7", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <Tooltip
                    cursor={{ fill: "rgba(255,255,255,0.04)" }}
                    formatter={(value: number) => [`${trimNumber(value)} 条`, "事件数量"]}
                    labelFormatter={(label) => `影响等级：${label}`}
                    contentStyle={CHART_TOOLTIP_CONTENT_STYLE}
                    itemStyle={CHART_TOOLTIP_ITEM_STYLE}
                    labelStyle={CHART_TOOLTIP_LABEL_STYLE}
                    wrapperStyle={CHART_TOOLTIP_WRAPPER_STYLE}
                  />
                  <Bar dataKey="count" radius={[8, 8, 0, 0]}>
                    {impactBreakdown.map((item) => (
                      <Cell key={item.impact} fill={item.fill} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </ChartShell>
          </Panel>
          <Panel title="宏观记忆" eyebrow="Memory">
            <div className="rounded-2xl border border-white/10 bg-white/[0.04] p-4 text-sm leading-7 text-slate-300 ring-hairline">
              {nonEmptyText(
                props.data?.latest_macro_daily_memory?.payload?.summary ?? props.news?.macro_daily_memory?.payload?.summary,
                "今天还没有形成正式的宏观日记忆。",
              )}
            </div>
          </Panel>
        </div>
        <Panel title="事件墙" eyebrow="Event Wall">
          <div className="space-y-3">
            {renderAssetCollection(
              macroEvents.slice(0, 10),
              (record) => <MacroEventCard key={record.asset_id} asset={record} />,
              "MEA 还没有提交新的正式事件。",
            )}
          </div>
        </Panel>
      </section>
    </section>
  );
}
