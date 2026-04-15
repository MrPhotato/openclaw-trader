import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Cell, ComposedChart, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { fetchAgentLatest, fetchExecutions, fetchMarketContext, fetchNews, fetchOverview, isStreamDisabled, openEventStream } from "./lib/api";
import { useMissionControlStore } from "./lib/store";
import type { AgentLatestData, AssetRecord, EventEnvelope, MarketContextData, OverviewData, ViewKey } from "./lib/types";

const agentPages = [
  {
    view: "pm",
    role: "pm",
    label: "PM",
    name: "Portfolio Manager",
    accent: "text-emerald-200",
    intro: "负责给出组合方向、风险预算和再检查节奏。这里展示的是正式策略，不是内部草稿。",
  },
  {
    view: "rt",
    role: "risk_trader",
    label: "RT",
    name: "Risk Trader",
    accent: "text-orange-200",
    intro: "负责把 PM 的组合框架转成可执行决策。重点看战术地图、风险锁和最新成交回执。",
  },
  {
    view: "mea",
    role: "macro_event_analyst",
    label: "MEA",
    name: "Macro & Event Analyst",
    accent: "text-sky-200",
    intro: "负责跟踪宏观与事件冲击，筛出真正会改变交易判断的新闻，而不是堆信息流。",
  },
  {
    view: "chief",
    role: "crypto_chief",
    label: "Chief",
    name: "Crypto Chief",
    accent: "text-amber-200",
    intro: "负责复盘、owner summary 和四个席位的会后学习。这里看的是当天这套系统学到了什么。",
  },
] as const;

const navItems: Array<{ key: ViewKey; label: string }> = [
  { key: "overview", label: "总览" },
  { key: "pm", label: "PM" },
  { key: "rt", label: "RT" },
  { key: "mea", label: "MEA" },
  { key: "chief", label: "Chief" },
];

const moduleLabels: Record<string, string> = {
  agent_gateway: "Agent Gateway",
  workflow_orchestrator: "工作流编排",
  trade_gateway: "交易网关",
  market_data: "市场数据",
  policy_risk: "风控",
  notification_service: "通知",
  memory_assets: "资产归档",
  news_events: "新闻事件",
  quant_intelligence: "量化洞察",
};

const DEFAULT_DISPLAY_EQUITY_USD = 1000;
const DISPLAY_LEVERAGE = 5;
type BalanceGranularity = "15m" | "1h" | "1d";
type BalancePoint = { label: string; equity: number; createdAtMs: number };

const CHART_TOOLTIP_CONTENT_STYLE = {
  backgroundColor: "rgba(9, 14, 27, 0.96)",
  border: "1px solid rgba(148, 163, 184, 0.22)",
  borderRadius: "14px",
  boxShadow: "0 18px 40px rgba(2, 6, 23, 0.55)",
  color: "#e2e8f0",
};

const CHART_TOOLTIP_ITEM_STYLE = { color: "#f8fafc", fontSize: 12 };
const CHART_TOOLTIP_LABEL_STYLE = { color: "#cbd5e1", fontSize: 12 };
const CHART_TOOLTIP_WRAPPER_STYLE = { zIndex: 20, outline: "none" as const };

export default function App() {
  const [balanceGranularity, setBalanceGranularity] = useState<BalanceGranularity>("1h");
  const [executionFeedExpanded, setExecutionFeedExpanded] = useState(false);
  const [eventFeedExpanded, setEventFeedExpanded] = useState(false);
  const chartViewportRef = useRef<HTMLDivElement | null>(null);
  const streamDisabled = isStreamDisabled();
  const activeView = useMissionControlStore((state) => state.activeView);
  const connectionState = useMissionControlStore((state) => state.connectionState);
  const liveEvents = useMissionControlStore((state) => state.liveEvents);
  const streamOverview = useMissionControlStore((state) => state.streamOverview);
  const setView = useMissionControlStore((state) => state.setView);
  const setConnectionState = useMissionControlStore((state) => state.setConnectionState);
  const setStreamPayload = useMissionControlStore((state) => state.setStreamPayload);

  const overviewQuery = useQuery({
    queryKey: ["overview"],
    queryFn: fetchOverview,
    refetchInterval: 15000,
  });
  const newsQuery = useQuery({
    queryKey: ["news"],
    queryFn: fetchNews,
    refetchInterval: 30000,
  });
  const executionsQuery = useQuery({
    queryKey: ["executions"],
    queryFn: fetchExecutions,
    refetchInterval: 15000,
  });
  const marketContextQuery = useQuery({
    queryKey: ["market-context"],
    queryFn: fetchMarketContext,
    refetchInterval: 30000,
  });
  const agentQueries = useQueries({
    queries: agentPages.map((agent) => ({
      queryKey: ["agent", agent.role],
      queryFn: () => fetchAgentLatest(agent.role),
      refetchInterval: 30000,
    })),
  });

  useEffect(() => {
    const close = openEventStream(setStreamPayload, setConnectionState);
    return close;
  }, [setConnectionState, setStreamPayload]);

  const overview = newerOverview(streamOverview, overviewQuery.data);
  const eventFeed = overview === streamOverview && liveEvents.length ? liveEvents : overview?.recent_events ?? [];
  const latestStrategy = overview?.latest_strategy?.payload ?? {};
  const latestPortfolio = overview?.latest_portfolio?.payload ?? {};
  const balanceSeries = buildBalanceHistory(overview?.portfolio_history ?? [], latestPortfolio, balanceGranularity);
  const balanceTicks = buildBalanceTicks(balanceSeries);
  const balanceDomain = buildBalanceDomain(balanceSeries);
  const balanceChartWidth = computeBalanceChartWidth(balanceSeries.length, balanceGranularity);
  const impactBreakdown = buildImpactBreakdown(newsQuery.data?.macro_events ?? []);
  const executionRecords = (executionsQuery.data?.results ?? overview?.recent_execution_results ?? []).slice(0, 8);
  const macroEventRecords = (newsQuery.data?.macro_events ?? overview?.current_macro_events ?? []).slice(0, 6);
  const agentDataByRole = Object.fromEntries(
    agentPages.map((agent, index) => [agent.role, agentQueries[index].data]),
  ) as Record<string, AgentLatestData | undefined>;
  const pmData = agentDataByRole.pm;
  const rtData = agentDataByRole.risk_trader;
  const meaData = agentDataByRole.macro_event_analyst;
  const chiefData = agentDataByRole.crypto_chief;

  useEffect(() => {
    const node = chartViewportRef.current;
    if (!node) {
      return;
    }

    const handleWheel = (event: WheelEvent) => {
      if (balanceSeries.length <= 1) {
        return;
      }
      event.preventDefault();
      event.stopPropagation();
      const delta = event.deltaX !== 0 ? event.deltaX : event.deltaY;
      node.scrollLeft += delta;
    };

    node.addEventListener("wheel", handleWheel, { passive: false });

    return () => {
      node.removeEventListener("wheel", handleWheel);
    };
  }, [balanceSeries.length]);

  // Keep the balance chart pinned to the most recent data on granularity or data changes,
  // like a stock chart that defaults to the right edge.
  useEffect(() => {
    const node = chartViewportRef.current;
    if (!node) {
      return;
    }
    // Defer to next frame so recharts has laid out before we scroll.
    const raf = requestAnimationFrame(() => {
      node.scrollLeft = node.scrollWidth;
    });
    return () => cancelAnimationFrame(raf);
  }, [balanceGranularity, balanceSeries.length, balanceChartWidth]);

  return (
    <div className="min-h-screen overflow-x-hidden bg-command-grid bg-[size:160px_160px,24px_24px,24px_24px] text-slate-100">
      <div className="mx-auto flex min-h-screen max-w-7xl min-w-0 flex-col gap-4 px-3 py-3 sm:gap-6 sm:px-6 sm:py-4 lg:px-8">
        <header className="glass-panel min-w-0 rounded-[24px] px-4 py-4 shadow-glow sm:rounded-[28px] sm:px-6 sm:py-5">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-2">
              <div className="flex items-center gap-3 text-xs uppercase tracking-[0.35em] text-ember">
                <span className="rounded-full border border-white/10 px-3 py-1 text-neon">OpenClaw</span>
                <span className="h-px w-16 animate-pulseLine bg-gradient-to-r from-neon via-white/30 to-transparent" />
                <span className="text-slate-400">公开看板</span>
              </div>
              <div>
                <h1 className="text-2xl font-semibold leading-none sm:text-5xl">Openclaw Trader AI交易</h1>
                <p className="mt-2 max-w-xl text-xs leading-5 text-slate-300 sm:text-base sm:leading-6">
                  <span className="text-slate-200">基于 OpenClaw 的 4 Agent Crypto永续合约交易集群实验，本金为 $1000。</span>
                  <a
                    href="https://github.com/MrPhotato/openclaw-trader"
                    target="_blank"
                    rel="noreferrer"
                    className="ml-2 inline-flex items-center text-neon underline decoration-neon/50 underline-offset-4 hover:text-white"
                  >
                    GitHub
                  </a>
                  <span className="ml-2 text-slate-500">·</span>
                  <span className="ml-2 text-slate-400">作者 MrPhotato</span>
                </p>
              </div>
            </div>
            <div className="grid gap-3 sm:grid-cols-4">
              <MetricBadge
                label={streamDisabled ? "更新方式" : "链路"}
                value={connectionStateLabel(connectionState, streamDisabled)}
                tone={streamBadgeTone(connectionState, streamDisabled)}
              />
              <MetricBadge
                label="事件"
                value={`${eventFeed.length} 条`}
                tone="text-slate-100"
              />
              <MetricBadge
                label="策略"
                value={strategyBadgeValue(latestStrategy)}
                tone="text-ember"
              />
              <MetricBadge
                label="席位"
                value={`${countActiveAgents(overview?.agent_sessions ?? [])}/4`}
                tone="text-slate-100"
              />
            </div>
          </div>
          <nav className="mt-5 flex flex-wrap gap-2">
            {navItems.map(({ key, label }) => (
              <button
                key={key}
                type="button"
                onClick={() => setView(key)}
                className={`rounded-full px-4 py-2 text-sm transition ${
                  activeView === key
                    ? "bg-ember text-ink shadow-lg shadow-ember/30"
                    : "border border-white/10 bg-white/5 text-slate-200 hover:border-white/20 hover:bg-white/10"
                }`}
              >
                {label}
              </button>
            ))}
          </nav>
        </header>

        {activeView === "overview" && (
          <section className="grid min-w-0 gap-4 sm:gap-6 lg:grid-cols-[1.25fr_0.95fr]" data-testid="overview-view">
            <div className="min-w-0 space-y-4 sm:space-y-6">
              <Panel title="账户余额轨迹">
                <div className="mb-4 grid gap-3 sm:grid-cols-2">
                  <SummaryPill
                    label="账户余额（当前总权益）"
                    value={usdCompactText(latestPortfolio["total_equity_usd"])}
                  />
                  <SummaryPill
                    label="当前杠杆"
                    value={configuredLeverageLabel(latestPortfolio)}
                  />
                </div>
                <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {buildNominalExposurePills(latestPortfolio, latestStrategy).map((item) => (
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
                <ChartShell>
                  <div className="grid min-w-0 grid-cols-[56px,minmax(0,1fr)] gap-2 sm:grid-cols-[72px,minmax(0,1fr)] sm:gap-3">
                    <FixedBalanceAxis ticks={balanceTicks} />
                    <div
                      ref={chartViewportRef}
                      data-testid="balance-chart-viewport"
                      className="w-full max-w-full overflow-x-auto overflow-y-hidden"
                      style={{ touchAction: "pan-x", overscrollBehaviorX: "contain", overscrollBehaviorY: "contain" }}
                    >
                      <div style={{ width: `${balanceChartWidth}px`, minWidth: "100%" }}>
                        <LineChart width={balanceChartWidth} height={260} data={balanceSeries} margin={{ top: 12, right: 8, bottom: 0, left: 0 }}>
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
                          <YAxis hide domain={balanceDomain} ticks={balanceTicks} />
                          <Tooltip
                            cursor={{ stroke: "rgba(113,246,209,0.35)" }}
                            formatter={(value: number) => [`$${trimNumber(value)}`, balanceWindowLabel(balanceGranularity)]}
                            labelFormatter={(label) => `时间：${label}`}
                            contentStyle={CHART_TOOLTIP_CONTENT_STYLE}
                            itemStyle={CHART_TOOLTIP_ITEM_STYLE}
                            labelStyle={CHART_TOOLTIP_LABEL_STYLE}
                            wrapperStyle={CHART_TOOLTIP_WRAPPER_STYLE}
                          />
                          <Line type="monotone" dataKey="equity" stroke="#71f6d1" strokeWidth={3} dot={false} connectNulls activeDot={{ r: 4 }} />
                        </LineChart>
                      </div>
                    </div>
                  </div>
                </ChartShell>
                <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
                  <div className="flex flex-wrap gap-2">
                    {([
                      ["15m", "15 分钟"],
                      ["1h", "1 小时"],
                      ["1d", "日线"],
                    ] as const).map(([key, label]) => (
                      <button
                        key={key}
                        type="button"
                        onClick={() => setBalanceGranularity(key)}
                        className={`rounded-full px-3 py-1.5 text-xs transition ${
                          balanceGranularity === key
                            ? "bg-neon/90 text-ink"
                            : "border border-white/10 bg-white/5 text-slate-300 hover:border-white/20 hover:bg-white/10"
                        }`}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                  <div className="text-[11px] leading-5 text-slate-500 sm:text-xs" data-testid="balance-viewport-caption">
                    {balanceScrollCaption(balanceSeries.length, balanceGranularity)}
                  </div>
                </div>
                <div className="mt-3 text-sm text-slate-400">
                  {balanceNarrative(latestPortfolio, balanceGranularity, balanceSeries)}
                </div>
              </Panel>

              <KlineChart marketContext={marketContextQuery.data} />

              <Panel title="系统脉搏">
                <div className="grid gap-3 sm:grid-cols-2">
                  <MetricCard
                    label="当前风险状态"
                    value={riskStateLabel(overview?.risk_overlay)}
                    detail={riskStateNarrative(overview?.risk_overlay, latestPortfolio)}
                  />
                  <MetricCard
                    label="最新策略方向"
                    value={portfolioModeLabel(latestStrategy["portfolio_mode"])}
                    detail={strategyFocusText(latestStrategy)}
                  />
                </div>
                <div className="mt-4 grid gap-3 xl:grid-cols-2">
                  {agentPages.map((agent) => (
                    <AgentPulseCard
                      key={agent.role}
                      agent={agent}
                      data={agentDataByRole[agent.role]}
                    />
                  ))}
                </div>
              </Panel>
            </div>

            <div className="min-w-0 space-y-4 sm:space-y-6">
              <Panel
                title="最新成交回执"
                action={
                  executionRecords.length > 3 ? (
                    <PanelToggleButton
                      expanded={executionFeedExpanded}
                      onToggle={() => setExecutionFeedExpanded((value) => !value)}
                      expandLabel="展开更多成交回执"
                      collapseLabel="收起更多成交回执"
                    />
                  ) : undefined
                }
              >
                  <div className="space-y-3" data-testid="overview-execution-disclosure">
                    {renderAssetCollection(
                      executionRecords.slice(0, 3),
                      (record) => <TradeBlotterCard key={record.asset_id} asset={record} latestPortfolio={latestPortfolio} />,
                      "最近还没有新的正式执行结果。",
                    )}
                    {executionFeedExpanded ? (
                      <div className="space-y-3">
                        {renderAssetCollection(
                          executionRecords.slice(3),
                          (record) => <TradeBlotterCard key={record.asset_id} asset={record} latestPortfolio={latestPortfolio} />,
                          "最近还没有新的正式执行结果。",
                        )}
                      </div>
                    ) : null}
                  </div>
              </Panel>
              <Panel
                title="高优先事件"
                action={
                  macroEventRecords.length > 3 ? (
                    <PanelToggleButton
                      expanded={eventFeedExpanded}
                      onToggle={() => setEventFeedExpanded((value) => !value)}
                      expandLabel="展开更多高优先事件"
                      collapseLabel="收起更多高优先事件"
                    />
                  ) : undefined
                }
              >
                  <div className="space-y-3" data-testid="overview-event-disclosure">
                    {renderAssetCollection(
                      macroEventRecords.slice(0, 3),
                      (record) => <MacroEventCard key={record.asset_id} asset={record} />,
                      "高影响事件会在这里排到最上面，当前还没有新的正式事件。",
                    )}
                    {eventFeedExpanded ? (
                      <div className="space-y-3">
                        {renderAssetCollection(
                          macroEventRecords.slice(3),
                          (record) => <MacroEventCard key={record.asset_id} asset={record} />,
                          "高影响事件会在这里排到最上面，当前还没有新的正式事件。",
                        )}
                      </div>
                    ) : null}
                  </div>
              </Panel>
            </div>
          </section>
        )}

        {activeView === "pm" && (
          <section className="space-y-4 sm:space-y-6" data-testid="pm-view">
            <AgentHero agent={agentPages[0]} data={pmData} />
            <section className="grid min-w-0 gap-4 sm:gap-6 lg:grid-cols-[1.05fr_0.95fr]">
              <Panel title="当前正式策略">
                <div className="space-y-4">
                  <Headline label="策略版本" value={strategyIdentity(latestStrategy)} />
                  <Headline label="组合模式" value={portfolioModeLabel(latestStrategy["portfolio_mode"])} />
                  <Headline label="策略重点" value={strategyFocusText(latestStrategy)} />
                  <Headline label="变更摘要" value={nonEmptyText(latestStrategy["change_summary"], "当前还没有显式写出的变更摘要。")} />
                  <Headline label="翻向条件" value={nonEmptyText(latestStrategy["flip_triggers"], "当前还没有写明翻向条件。")} />
                  <Headline label="失效条件" value={nonEmptyText(latestStrategy["portfolio_invalidation"], "暂无明确失效条件。")} />
                </div>
              </Panel>
              <Panel title="目标与复核">
                <div className="grid gap-3">
                  {renderCollection(
                    readTargets(latestStrategy),
                    (target) => (
                      <div key={target.label} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                        <div className="flex items-center justify-between gap-3">
                          <span className="font-medium">{target.label}</span>
                          <span className="text-xs text-slate-400">{target.direction}</span>
                        </div>
                        <div className="mt-2 text-sm text-slate-300">{target.detail}</div>
                      </div>
                    ),
                    "PM 还没有提交具体 target，系统会先维持空白。",
                  )}
                </div>
                <div className="mt-4">
                  <SectionLabel label="下一轮复核" />
                  <div className="mt-3 space-y-2">
                    {renderCollection(
                      readRechecks(latestStrategy),
                      (item) => (
                        <div key={item.label} className="rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-3 text-sm text-slate-300">
                          <div className="font-medium text-slate-200">{item.label}</div>
                          <div className="mt-1 text-xs text-slate-400">{item.detail}</div>
                        </div>
                      ),
                      "当前没有排程中的复核节点。",
                    )}
                  </div>
                </div>
              </Panel>
            </section>
          </section>
        )}

        {activeView === "rt" && (
          <section className="space-y-4 sm:space-y-6" data-testid="rt-view">
            <AgentHero agent={agentPages[1]} data={rtData} />
            <section className="grid min-w-0 gap-4 sm:gap-6 lg:grid-cols-[minmax(0,1.65fr)_minmax(300px,0.72fr)]">
              <Panel title="RT 战术地图">
                <RtTacticalBoard data={rtData} latestStrategy={latestStrategy} />
              </Panel>
              <div className="min-w-0 space-y-4 sm:space-y-6">
                <Panel title="最新执行回执">
                  <div className="space-y-3">
                    {renderAssetCollection(
                      (executionsQuery.data?.results ?? overview?.recent_execution_results ?? []).slice(0, 4),
                      (record) => <TradeBlotterCard key={record.asset_id} asset={record} latestPortfolio={latestPortfolio} />,
                      "RT 还没有新的正式执行结果。",
                    )}
                  </div>
                </Panel>
                <Panel title="判断记录">
                  <div className="space-y-3">
                    {renderCollection(
                      (rtData?.recent_execution_thoughts ?? []).slice(0, 4),
                      (thought, index) => <ThoughtCard key={`${thought.symbol ?? "thought"}-${index}`} thought={thought} />,
                      "RT 还没有沉淀出可展示的近期思路记录。",
                    )}
                  </div>
                </Panel>
              </div>
            </section>
          </section>
        )}

        {activeView === "mea" && (
          <section className="space-y-4 sm:space-y-6" data-testid="mea-view">
            <AgentHero agent={agentPages[2]} data={meaData} />
            <section className="grid min-w-0 gap-4 sm:gap-6 lg:grid-cols-[0.92fr_1.08fr]">
              <div className="min-w-0 space-y-4 sm:space-y-6">
                <Panel title="影响分布">
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
                <Panel title="宏观记忆">
                  <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm leading-7 text-slate-300">
                    {nonEmptyText(
                      meaData?.latest_macro_daily_memory?.payload?.summary ?? newsQuery.data?.macro_daily_memory?.payload?.summary,
                      "今天还没有形成正式的宏观日记忆。",
                    )}
                  </div>
                </Panel>
              </div>
              <Panel title="事件墙">
                <div className="space-y-3">
                  {renderAssetCollection(
                    (newsQuery.data?.macro_events ?? meaData?.recent_macro_events ?? []).slice(0, 10),
                    (record) => <MacroEventCard key={record.asset_id} asset={record} />,
                    "MEA 还没有提交新的正式事件。",
                  )}
                </div>
              </Panel>
            </section>
          </section>
        )}

        {activeView === "chief" && (
          <section className="space-y-4 sm:space-y-6" data-testid="chief-view">
            <AgentHero agent={agentPages[3]} data={chiefData} />
            <ChiefRetroTimeline data={chiefData} agentPages={agentPages} agentDataByRole={agentDataByRole} />
          </section>
        )}
      </div>
    </div>
  );
}

function Panel(props: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <article className="glass-panel min-w-0 overflow-hidden rounded-[24px] p-4 shadow-glow sm:rounded-[28px] sm:p-5">
      <div className="mb-4 flex items-start justify-between gap-3 sm:mb-5">
        <h2 className="text-xl font-semibold sm:text-2xl">{props.title}</h2>
        {props.action ? <div className="shrink-0">{props.action}</div> : null}
      </div>
      {props.children}
    </article>
  );
}

function MetricBadge(props: { label: string; value: string; tone: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
      <div className="text-[11px] tracking-[0.2em] text-slate-500">{props.label}</div>
      <div className={`mt-2 text-sm font-medium ${props.tone}`}>{props.value}</div>
    </div>
  );
}

function MetricCard(props: { label: string; value: string; detail: string }) {
  return (
    <div className="glass-panel rounded-[24px] p-4">
      <div className="text-[11px] tracking-[0.2em] text-slate-500">{props.label}</div>
      <div className="mt-3 text-3xl font-semibold">{props.value}</div>
      <div className="mt-2 text-xs leading-5 text-slate-400">{props.detail}</div>
    </div>
  );
}

function SummaryPill(props: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
      <div className="text-[10px] tracking-[0.2em] text-slate-500">{props.label}</div>
      <div className="mt-1 text-lg font-semibold text-slate-100 sm:text-xl">{props.value}</div>
    </div>
  );
}

function CoinExposurePill(props: {
  coin: string;
  direction?: string;
  directionTone?: "long" | "short" | "flat" | "muted";
  exposure: string;
  strategyExposure?: string;
  share: string;
  strategyShare?: string;
}) {
  const toneClass =
    props.directionTone === "long"
      ? "text-emerald-300"
      : props.directionTone === "short"
        ? "text-rose-300"
        : props.directionTone === "flat"
          ? "text-slate-300"
          : "text-slate-500";
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-[10px] tracking-[0.2em] text-slate-500">{props.coin}</div>
        {props.direction ? (
          <div className={`text-[11px] font-medium ${toneClass}`}>{props.direction}</div>
        ) : null}
      </div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-2 text-base font-medium text-slate-200">
        <span>{props.exposure}</span>
        {props.strategyExposure ? (
          <span className="text-xs font-normal text-slate-500">/ 策略 {props.strategyExposure}</span>
        ) : null}
      </div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-2 text-xs text-slate-400">
        <span>{props.share}</span>
        {props.strategyShare ? (
          <span className="text-slate-500">/ 策略 {props.strategyShare}</span>
        ) : null}
      </div>
    </div>
  );
}

function ChartShell(props: { children: ReactNode }) {
  return <div className="min-w-0 rounded-[20px] border border-white/10 bg-white/5 p-2 sm:rounded-[24px] sm:p-3">{props.children}</div>;
}

function FixedBalanceAxis(props: { ticks: number[] }) {
  const labels = props.ticks.length > 0 ? [...props.ticks].reverse() : [0];

  return (
    <div
      data-testid="balance-chart-fixed-axis"
      className="grid h-[260px] grid-rows-[1fr_32px] border-r border-white/10 pr-2 sm:pr-3"
    >
      <div
        className={`flex min-h-0 flex-col text-right text-[10px] text-slate-500 sm:text-xs ${
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

type KlineTimeframe = "15m" | "1h" | "4h" | "1d";

const KLINE_TIMEFRAME_TO_BACKEND: Record<KlineTimeframe, string> = {
  "15m": "15m",
  "1h": "1h",
  "4h": "4h",
  "1d": "24h",
};

const KLINE_TIMEFRAME_LABEL: Record<KlineTimeframe, string> = {
  "15m": "15 分钟",
  "1h": "1 小时",
  "4h": "4 小时",
  "1d": "日线",
};

type CandlePoint = {
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

function KlineChart(props: { marketContext?: MarketContextData }) {
  const contexts = props.marketContext?.market_context ?? {};
  const availableCoins = Object.keys(contexts);
  const [coin, setCoin] = useState<string>("");
  const [timeframe, setTimeframe] = useState<KlineTimeframe>("1h");
  const viewportRef = useRef<HTMLDivElement | null>(null);

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

  useEffect(() => {
    const node = viewportRef.current;
    if (!node) {
      return;
    }
    const raf = requestAnimationFrame(() => {
      node.scrollLeft = node.scrollWidth;
    });
    return () => cancelAnimationFrame(raf);
  }, [activeCoin, timeframe, candles.length, chartWidth]);

  if (availableCoins.length === 0) {
    return (
      <Panel title="行情 K 线">
        <EmptyState message="还没有拿到行情序列，等待下一轮市场数据采集。" />
      </Panel>
    );
  }

  return (
    <Panel title="行情 K 线">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-2" data-testid="kline-coin-tabs">
          {availableCoins.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setCoin(option)}
              className={`rounded-full px-3 py-1.5 text-xs transition ${
                option === activeCoin
                  ? "bg-neon/90 text-ink"
                  : "border border-white/10 bg-white/5 text-slate-300 hover:border-white/20 hover:bg-white/10"
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
                  ? "bg-neon/90 text-ink"
                  : "border border-white/10 bg-white/5 text-slate-300 hover:border-white/20 hover:bg-white/10"
              }`}
            >
              {KLINE_TIMEFRAME_LABEL[key]}
            </button>
          ))}
        </div>
      </div>
      <div className="mb-3 flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm text-slate-300">
        <span className="text-base font-semibold text-slate-100">{activeCoin}</span>
        {lastCandle ? <span className="text-slate-200">最新 ${trimNumber(lastCandle.close)}</span> : null}
        {changePct !== null ? (
          <span className={changePct >= 0 ? "text-emerald-300" : "text-rose-300"}>
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

function FixedKlineAxis(props: { ticks: number[] }) {
  const labels = props.ticks.length > 0 ? [...props.ticks].reverse() : [0];
  return (
    <div
      data-testid="kline-chart-fixed-axis"
      className="grid h-[260px] grid-rows-[1fr_32px] border-r border-white/10 pr-2 sm:pr-3"
    >
      <div
        className={`flex min-h-0 flex-col text-right text-[10px] text-slate-500 sm:text-xs ${
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
    <div
      style={CHART_TOOLTIP_CONTENT_STYLE}
      className="space-y-1 px-3 py-2 text-xs"
    >
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

function TradeBlotterCard(props: { asset: AssetRecord; latestPortfolio: Record<string, unknown> }) {
  const fill = firstFill(props.asset);
  const leverage = currentPositionLeverage(props.asset, props.latestPortfolio);
  const executedNotional = actualFilledNotional(props.asset);
  const plannedNotional = toNumber(props.asset.payload["notional_usd"]);
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium">
            {tradeHeadline(props.asset)}
          </div>
          <div className="mt-1 text-xs text-slate-400">{tradeTimeLabel(props.asset)}</div>
        </div>
        <div className={executionRecordSuccess(props.asset) ? "text-neon" : "text-red-300"}>{executionRecordStatus(props.asset)}</div>
      </div>
      <div className="mt-3 grid gap-2 text-sm text-slate-300 sm:grid-cols-2">
        <div>交易方向：{tradeVerb(props.asset)}</div>
        <div>成交金额：{executedNotional !== null ? usdText(executedNotional) : usdText(props.asset.payload["notional_usd"])}</div>
        <div>成交价：{fill?.price ? `$${trimNumber(fill.price)}` : "未回传"}</div>
        <div>成交数量：{fill?.size ?? "未回传"}</div>
        <div>当前杠杆：{leverage}</div>
      </div>
      {executedNotional !== null && plannedNotional !== null && Math.abs(executedNotional - plannedNotional) > 0.01 ? (
        <div className="mt-2 text-xs text-slate-400">计划金额：{usdText(plannedNotional)}</div>
      ) : null}
      <div className="mt-2 text-xs text-slate-500">{executionRecordMeta(props.asset)}</div>
    </div>
  );
}

function EventRow(props: { event: EventEnvelope }) {
  const summary = summarizeEvent(props.event);
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-sm font-medium">{summary.title}</div>
          <div className="mt-1 text-xs text-slate-400">{summary.detail}</div>
        </div>
        <div className="text-right">
          <div className="text-xs text-slate-300">{moduleLabels[props.event.source_module] ?? props.event.source_module}</div>
          <div className="mt-1 text-xs text-slate-500">{formatTime(props.event.occurred_at)}</div>
        </div>
      </div>
    </div>
  );
}

function Headline(props: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] tracking-[0.2em] text-slate-500">{props.label}</div>
      <div className="mt-1 text-base text-slate-100">{props.value}</div>
    </div>
  );
}

function SectionLabel(props: { label: string }) {
  return <div className="text-[11px] tracking-[0.2em] text-slate-500">{props.label}</div>;
}

function EmptyState(props: { message: string }) {
  return <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.03] px-4 py-5 text-sm text-slate-400">{props.message}</div>;
}

function PanelToggleButton(props: {
  expanded: boolean;
  onToggle: () => void;
  expandLabel: string;
  collapseLabel: string;
}) {
  return (
    <button
      type="button"
      onClick={props.onToggle}
      aria-label={props.expanded ? props.collapseLabel : props.expandLabel}
      className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs text-slate-200 transition hover:border-white/20 hover:bg-white/10"
    >
      {props.expanded ? "收起" : "展开更多"}
    </button>
  );
}

function AgentHero(props: { agent: (typeof agentPages)[number]; data?: AgentLatestData }) {
  const sessionStatus = String(props.data?.session?.status ?? "offline");
  const latestType = String(props.data?.latest_asset?.asset_type ?? "none");
  const latestAt = latestAssetTimestamp(props.data);

  return (
    <section className="glass-panel rounded-[24px] px-4 py-5 shadow-glow sm:rounded-[28px] sm:px-5">
      <div className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
        <div className="space-y-3">
          <div className={`text-xs uppercase tracking-[0.32em] ${props.agent.accent}`}>{props.agent.label}</div>
          <div>
            <h2 className="text-2xl font-semibold sm:text-4xl">{props.agent.name}</h2>
            <p className="mt-2 max-w-2xl text-sm leading-7 text-slate-300">{props.agent.intro}</p>
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <HeroMetric label="会话状态" value={sessionStatusLabel(sessionStatus)} tone={props.agent.accent} />
          <HeroMetric label="最近产物" value={assetTypeLabel(latestType)} tone="text-slate-100" />
          <HeroMetric label="最近活跃" value={latestAt} tone="text-slate-200" />
        </div>
      </div>
    </section>
  );
}

function HeroMetric(props: { label: string; value: string; tone: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.05] px-4 py-3">
      <div className="text-[10px] tracking-[0.22em] text-slate-500">{props.label}</div>
      <div className={`mt-2 text-sm font-medium ${props.tone}`}>{props.value}</div>
    </div>
  );
}

function AgentPulseCard(props: { agent: (typeof agentPages)[number]; data?: AgentLatestData }) {
  const sessionStatus = String(props.data?.session?.status ?? "offline");
  const latestAsset = props.data?.latest_asset;
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className={`text-sm font-medium ${props.agent.accent}`}>{props.agent.label}</div>
          <div className="mt-1 text-xs text-slate-400">{props.agent.name}</div>
        </div>
        <div className="text-xs text-slate-500">{sessionStatusLabel(sessionStatus)}</div>
      </div>
      <div className="mt-3 text-sm text-slate-200">{assetPreview(latestAsset)}</div>
      <div className="mt-2 text-xs text-slate-500">
        {latestAsset ? `${assetTypeLabel(latestAsset.asset_type)} · ${formatTime(latestAsset.created_at)}` : "还没有新的正式产物。"}
      </div>
    </div>
  );
}

function MacroEventCard(props: { asset: AssetRecord }) {
  const impact = String(props.asset.payload["impact_level"] ?? "low");
  const refs = Array.isArray(props.asset.payload["source_refs"]) ? props.asset.payload["source_refs"] : [];
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium">{newsCategoryLabel(props.asset.payload["category"])}</div>
          <div className="mt-1 text-xs text-slate-500">{formatTime(props.asset.created_at)}</div>
        </div>
        <span className={impactTone(impact)}>{impactLabel(impact)}</span>
      </div>
      <div className="mt-3 text-sm leading-7 text-slate-300">{nonEmptyText(props.asset.payload["summary"], "没有可展示的事件摘要。")}</div>
      <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-slate-500">
        {refs.length ? <span>{refs.length} 个来源已归档</span> : <span>结构化事件已入库</span>}
      </div>
    </div>
  );
}

function RtTacticalBoard(props: { data?: AgentLatestData; latestStrategy: Record<string, unknown> }) {
  const brief = asRecord(props.data?.tactical_brief);
  const trigger = asRecord(brief?.trigger);
  const coins = Array.isArray(brief?.coins) ? brief?.coins : [];
  const mapNote = typeof brief?.map_note === "string" ? brief.map_note : "";
  const mapGeneratedAt = typeof brief?.map_generated_at === "string" ? brief.map_generated_at : "";
  const latestMapGeneratedAt = typeof brief?.latest_map_generated_at === "string" ? brief.latest_map_generated_at : "";
  const latestMapRefreshReason = typeof brief?.latest_map_refresh_reason === "string" ? brief.latest_map_refresh_reason : "";
  if (!brief && !(props.data?.recent_execution_thoughts?.length || readTargets(props.latestStrategy).length)) {
    return <EmptyState message="RT 还没有形成公开可读的战术板，等第一轮执行或策略输出后会自动出现。" />;
  }

  return (
    <div className="space-y-4">
      {mapNote ? (
        <div className="rounded-2xl border border-amber-300/20 bg-amber-300/10 px-4 py-3 text-sm leading-6 text-amber-100">
          <div>{mapNote}</div>
          {mapGeneratedAt ? <div className="mt-1 text-xs text-amber-100/70">当前地图时间：{formatTime(mapGeneratedAt)}</div> : null}
          {latestMapGeneratedAt ? (
            <div className="mt-1 text-xs text-amber-100/70">
              最近刷新时间：{formatTime(latestMapGeneratedAt)}
              {latestMapRefreshReason ? ` · ${latestMapRefreshReason}` : ""}
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="rounded-[26px] border border-white/10 bg-white/[0.04] p-4 sm:p-5">
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)]">
          <div className="rounded-2xl border border-white/10 bg-white/[0.05] p-4">
            <div className="text-[11px] tracking-[0.2em] text-slate-500">这轮在做什么</div>
            <div className="mt-3 text-xl font-semibold leading-9 text-slate-50 sm:text-2xl">
              {rtDeskHeadline(brief, props.latestStrategy)}
            </div>
            <div className="mt-3 text-sm leading-7 text-slate-300">
              {rtNoviceGuide(brief, props.latestStrategy)}
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              {rtMetadataPills(brief, trigger).map((item) => (
                <div key={item} className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1.5 text-xs text-slate-300">
                  {item}
                </div>
              ))}
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
            <TacticalMetric label="当前打法" value={rtPortfolioPostureLabel(brief?.portfolio_posture, props.latestStrategy["portfolio_mode"])} />
            <TacticalMetric label="风险要求" value={rtRiskBiasLabel(brief?.risk_bias)} />
            <TacticalMetric label="下次复看" value={nonEmptyText(brief?.next_review_hint, "等待下一次 cadence。")} />
          </div>
        </div>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {renderCollection(
          coins,
          (coin, index) => <RtTacticalCard key={`${coin.coin ?? "coin"}-${index}`} coin={coin} />,
          "当前还没有按币种拆开的战术摘要。",
        )}
      </div>
    </div>
  );
}

function TacticalMetric(props: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="text-[11px] tracking-[0.2em] text-slate-500">{props.label}</div>
      <div className="mt-2 text-sm leading-7 text-slate-100">{props.value}</div>
    </div>
  );
}

function RtTacticalCard(props: { coin: Record<string, unknown> }) {
  const posture = rtWorkingPostureLabel(props.coin.working_posture);
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-lg font-semibold text-slate-100">{nonEmptyText(props.coin.coin, "UNKNOWN")}</div>
          <div className="mt-1 text-xs text-slate-500">这一栏只看这个币现在偏向怎么做。</div>
        </div>
        <span className={`rounded-full px-3 py-1 text-xs font-medium ${rtWorkingPostureTone(props.coin.working_posture)}`}>{posture}</span>
      </div>
      <div className="mt-4 space-y-4 text-sm leading-7 text-slate-300">
        <RtDecisionBlock label="当前判断" value={compactText(nonEmptyText(props.coin.base_case, "暂无可展示文本。"), 180)} />
        <div className="grid gap-3 sm:grid-cols-2">
          <RtDecisionBlock label="更可能加仓" value={compactText(nonEmptyText(props.coin.preferred_add_condition, "暂无"), 120)} />
          <RtDecisionBlock label="更可能减仓" value={compactText(nonEmptyText(props.coin.preferred_reduce_condition, "暂无"), 120)} />
        </div>
        <RtDecisionBlock label="什么时候叫 PM 重看" value={compactText(nonEmptyText(props.coin.force_pm_recheck_condition, "暂无"), 140)} />
        <div className="grid gap-2 text-xs text-slate-400 sm:grid-cols-2">
          <RtQuickReference label="止盈参考" value={compactText(nonEmptyText(props.coin.reference_take_profit_condition, "暂无"), 80)} />
          <RtQuickReference label="止损参考" value={compactText(nonEmptyText(props.coin.reference_stop_loss_condition, "暂无"), 80)} />
          <RtQuickReference label="禁做区" value={compactText(nonEmptyText(props.coin.no_trade_zone, "暂无"), 80)} />
          <RtQuickReference label="下一步" value={compactText(nonEmptyText(props.coin.next_focus, "继续观察"), 80)} />
        </div>
      </div>
    </div>
  );
}

function RtDecisionBlock(props: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-3">
      <div className="text-[11px] tracking-[0.18em] text-slate-500">{props.label}</div>
      <div className="mt-2 text-sm leading-7 text-slate-200">{props.value}</div>
    </div>
  );
}

function RtQuickReference(props: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2">
      <div className="text-[10px] tracking-[0.18em] text-slate-500">{props.label}</div>
      <div className="mt-1 text-xs leading-5 text-slate-300">{props.value}</div>
    </div>
  );
}

function ThoughtCard(props: { thought: Record<string, unknown> }) {
  const result = asRecord(props.thought.execution_result);
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-medium text-slate-100">
            {nonEmptyText(props.thought.symbol, "UNKNOWN")} · {actionLabel(props.thought.action)} · {directionLabel(props.thought.direction)}
          </div>
          <div className="mt-1 text-xs text-slate-500">{formatTime(String(props.thought.generated_at_utc ?? ""))}</div>
        </div>
        <div className="text-xs text-slate-400">{urgencyLabel(props.thought.urgency)}</div>
      </div>
      <div className="mt-3 text-sm leading-7 text-slate-300">{nonEmptyText(props.thought.reason, "这轮没有留下额外的判断说明。")}</div>
      <div className="mt-3 grid gap-2 text-xs text-slate-400 sm:grid-cols-2">
        <div>止盈参考：{nonEmptyText(props.thought.reference_take_profit_condition, "暂无")}</div>
        <div>止损参考：{nonEmptyText(props.thought.reference_stop_loss_condition, "暂无")}</div>
      </div>
      <div className="mt-3 text-xs text-slate-500">
        {result ? executionThoughtResultText(result) : "执行结果尚未回写，当前只展示当时的判断。"}
      </div>
    </div>
  );
}

/* ── Chief Retro Timeline ─────────────────────────────────────── */

const ROLE_LABEL: Record<string, string> = { pm: "PM", risk_trader: "RT", macro_event_analyst: "MEA", crypto_chief: "Chief" };
const GRADE_TONE: Record<string, string> = {
  A: "text-emerald-300", "A+": "text-emerald-300", "A-": "text-emerald-300",
  B: "text-sky-300", "B+": "text-sky-300", "B-": "text-sky-300",
  C: "text-amber-300", "C+": "text-amber-300", "C-": "text-amber-300",
  D: "text-red-400", "D+": "text-red-400", "D-": "text-red-400",
  F: "text-red-500",
};

function ChiefRetroTimeline(props: {
  data?: AgentLatestData;
  agentPages: readonly typeof agentPages[number][];
  agentDataByRole: Record<string, AgentLatestData | undefined>;
}) {
  const { data } = props;
  const chain = data?.retro_chain;
  const retro = data?.latest_chief_retro ?? data?.latest_asset;
  const retroPayload = asRecord(retro?.payload);

  if (!retro && !chain) {
    return (
      <Panel title="复盘时间线">
        <EmptyState message="还没有已完成的复盘记录。" />
      </Panel>
    );
  }

  const rc = chain?.retro_case ? asRecord(chain.retro_case) : null;
  const briefs = chain?.briefs ?? [];
  const directives = chain?.learning_directives ?? [];
  const learningResults = Array.isArray(retroPayload?.learning_results) ? retroPayload.learning_results as Record<string, unknown>[] : [];
  const rootCauseRanking = Array.isArray(retroPayload?.root_cause_ranking) ? retroPayload.root_cause_ranking as string[] : [];
  const roleJudgements = asRecord(retroPayload?.role_judgements);
  const ownerSummary = typeof retroPayload?.owner_summary === "string" ? retroPayload.owner_summary : "";
  const challengePrompts = normalizeRetroChallengePrompts(rc?.challenge_prompts);
  const learningDirectiveEmptyMessage = hasTextualLearningSection(ownerSummary)
    ? "这轮只在文本里写了学习要求，没提交结构化 learning_directives。"
    : "此次复盘没有生成学习指令。";
  const learningResultEmptyMessage = directives.length > 0
    ? "学习指令已生成，但学习结果尚未回写。"
    : hasTextualLearningSection(ownerSummary)
      ? "这轮没有结构化学习指令，所以也没有可核验的学习落实记录。"
      : "学习结果尚未回写。";
  const learningChain = chiefLearningChainState({
    ownerSummary,
    directives,
    learningResults,
    learningCompleted: retroPayload?.learning_completed === true,
  });

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* ① 复盘准备 */}
      <RetroPhasePanel
        step={1}
        title="复盘准备"
        timestamp={rc ? formatTime(String(rc.created_at_utc ?? rc.created_at ?? "")) : ""}
      >
        {rc ? (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-3">
              <HeroMetric label="复盘日期" value={String(rc.case_day_utc ?? "—")} tone="text-slate-100" />
              <HeroMetric label="目标收益" value={`${rc.target_return_pct ?? 1}%`} tone="text-amber-200" />
            </div>
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="text-xs tracking-widest text-slate-500 mb-2">核心问题</div>
              <div className="text-sm font-medium text-slate-100">{nonEmptyText(rc.primary_question, "—")}</div>
            </div>
            {typeof rc.objective_summary === "string" && rc.objective_summary && (
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <div className="text-xs tracking-widest text-slate-500 mb-2">客观摘要</div>
                <div className="text-sm leading-7 text-slate-300 whitespace-pre-line">{String(rc.objective_summary)}</div>
              </div>
            )}
            {challengePrompts.length > 0 && (
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <div className="text-xs tracking-widest text-slate-500 mb-3">挑战提示</div>
                <div className="space-y-2">
                  {challengePrompts.map((prompt, i) => (
                    <div key={i} className="flex gap-2 text-sm">
                      {prompt.label ? <span className="shrink-0 font-medium text-slate-400">{prompt.label}:</span> : null}
                      <span className="text-slate-300">{prompt.text}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : (
          <EmptyState message="此次复盘没有关联到 retro case。" />
        )}
      </RetroPhasePanel>

      {/* ② 角色自述 */}
      <RetroPhasePanel step={2} title="角色自述" timestamp="">
        {briefs.length > 0 ? (
          <div className="grid gap-4 lg:grid-cols-3">
            {briefs.map((brief) => {
              const b = asRecord(brief) ?? {};
              const role = String(b.agent_role ?? "");
              return (
                <div key={`${role}-${b.brief_id}`} className="rounded-2xl border border-white/10 bg-white/5 p-4 space-y-3">
                  <div className="flex items-center gap-2">
                    <span className="text-base font-semibold text-slate-100">{ROLE_LABEL[role] ?? role}</span>
                    <span className="text-xs text-slate-500">{formatTime(String(b.created_at_utc ?? ""))}</span>
                  </div>
                  <BriefField label="根因分析" value={b.root_cause} />
                  <BriefField label="自我批评" value={b.self_critique} />
                  <BriefField label="互相挑战" value={b.cross_role_challenge} />
                  <BriefField label="明日改进" value={b.tomorrow_change} />
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyState message="此次复盘没有收到角色自述 brief。" />
        )}
      </RetroPhasePanel>

      {/* ③ Chief 综合 */}
      <RetroPhasePanel
        step={3}
        title="Chief 综合判断"
        timestamp={retro ? formatTime(retro.created_at) : ""}
      >
        {retroPayload ? (
          <div className="space-y-4">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm leading-7 text-slate-300 whitespace-pre-line">
              {nonEmptyText(retroPayload.owner_summary, "此次复盘还没有 owner summary。")}
            </div>
            {rootCauseRanking.length > 0 && (
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <div className="text-xs tracking-widest text-slate-500 mb-3">根因排序</div>
                <ol className="list-decimal list-inside space-y-1 text-sm text-slate-300">
                  {rootCauseRanking.map((cause, i) => (
                    <li key={i}>{stripLeadingOrdinal(String(cause))}</li>
                  ))}
                </ol>
              </div>
            )}
            {roleJudgements && (
              <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
                <div className="text-xs tracking-widest text-slate-500 mb-3">角色裁决</div>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  {Object.entries(roleJudgements).map(([role, judgement]) => {
                    const parsed = parseRoleJudgement(judgement);
                    return (
                      <div key={role} className="rounded-xl border border-white/5 bg-white/[0.03] p-3">
                        <div className="text-xs text-slate-500">{ROLE_LABEL[role] ?? role}</div>
                        {parsed.grade ? (
                          <>
                            <div className={`mt-1 text-2xl font-bold ${GRADE_TONE[parsed.grade] ?? "text-slate-200"}`}>{parsed.grade}</div>
                            {parsed.comment ? <div className="mt-2 text-xs leading-5 text-slate-400">{parsed.comment}</div> : null}
                          </>
                        ) : (
                          <div className="mt-2 text-sm leading-6 text-slate-300">{parsed.comment || "暂无结构化裁决。"}</div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            <div className="grid gap-3 sm:grid-cols-3">
              <HeroMetric label="复盘模式" value={chiefRetroModeLabel(retroPayload?.round_count)} tone="text-slate-100" />
              <HeroMetric label="学习链路" value={learningChain.value} tone={learningChain.tone} />
              <HeroMetric label="复盘时间" value={retro ? formatTime(retro.created_at) : "—"} tone="text-slate-200" />
            </div>
          </div>
        ) : (
          <EmptyState message="Chief 还没有提交综合判断。" />
        )}
      </RetroPhasePanel>

      {/* ④ 学习指令 */}
      <RetroPhasePanel step={4} title="学习指令" timestamp="">
        {directives.length > 0 ? (
          <div className="space-y-3">
            {directives.map((dir) => {
              const d = asRecord(dir) ?? {};
              const role = String(d.agent_role ?? "");
              return (
                <div key={String(d.directive_id ?? role)} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="rounded-full bg-amber-500/20 px-2 py-0.5 text-xs font-medium text-amber-200">{ROLE_LABEL[role] ?? role}</span>
                  </div>
                  <div className="text-sm text-slate-200 leading-7">{nonEmptyText(d.directive, "无具体指令。")}</div>
                  {typeof d.rationale === "string" && d.rationale && (
                    <div className="mt-2 text-xs text-slate-500">依据：{String(d.rationale)}</div>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyState message={learningDirectiveEmptyMessage} />
        )}
      </RetroPhasePanel>

      {/* ⑤ 学习落实 */}
      <RetroPhasePanel step={5} title="学习落实" timestamp="">
        {learningResults.length > 0 ? (
          <div className="space-y-3">
            {learningResults.map((item, i) => {
              const record = asRecord(item) ?? {};
              const role = String(record.agent_role ?? "agent");
              return (
                <div key={`${role}-${i}`} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                  <div className="font-medium text-slate-100">{ROLE_LABEL[role] ?? role.toUpperCase()} 学习记录</div>
                  <div className="mt-2 text-sm text-slate-300 leading-7">{nonEmptyText(record.learning_summary, "本轮没有写出额外的学习摘要。")}</div>
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyState message={learningResultEmptyMessage} />
        )}
      </RetroPhasePanel>

      {/* 席位状态 */}
      <Panel title="席位状态">
        <div className="grid gap-3">
          {props.agentPages.map((agent) => (
            <AgentPulseCard
              key={agent.role}
              agent={agent}
              data={props.agentDataByRole[agent.role]}
            />
          ))}
        </div>
      </Panel>
    </div>
  );
}

function RetroPhasePanel(props: { step: number; title: string; timestamp: string; children: ReactNode }) {
  return (
    <article className="glass-panel min-w-0 overflow-hidden rounded-[24px] shadow-glow sm:rounded-[28px]">
      <div className="flex items-center gap-3 border-b border-white/5 px-4 py-3 sm:px-5">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-500/20 text-xs font-bold text-amber-200">
          {props.step}
        </span>
        <h2 className="text-lg font-semibold sm:text-xl">{props.title}</h2>
        {props.timestamp && (
          <span className="ml-auto text-xs text-slate-500">{props.timestamp}</span>
        )}
      </div>
      <div className="p-4 sm:p-5">{props.children}</div>
    </article>
  );
}

function BriefField(props: { label: string; value: unknown }) {
  const text = typeof props.value === "string" ? props.value.trim() : "";
  if (!text) return null;
  return (
    <div>
      <div className="text-[11px] tracking-widest text-slate-500 mb-1">{props.label}</div>
      <div className="text-sm leading-6 text-slate-300 whitespace-pre-line">{text}</div>
    </div>
  );
}

function buildImpactBreakdown(records: AssetRecord[]) {
  const counts = new Map<string, number>();
  for (const record of records) {
    const impact = String(record.payload["impact_level"] ?? "low");
    counts.set(impact, (counts.get(impact) ?? 0) + 1);
  }
  return ["high", "medium", "low"].map((impact) => ({
    impact: impactLabel(impact),
    count: counts.get(impact) ?? 0,
    fill: impact === "high" ? "#ff7d45" : impact === "medium" ? "#ffe066" : "#71f6d1",
  }));
}

function readTargets(strategy: Record<string, unknown>) {
  const targets = Array.isArray(strategy.targets) ? strategy.targets : [];
  return targets.slice(0, 6).map((target) => {
    const item = target as Record<string, unknown>;
    const band = Array.isArray(item.target_exposure_band_pct) ? item.target_exposure_band_pct : [];
    return {
      label: String(item.symbol ?? "UNKNOWN"),
      direction: directionLabel(item.direction),
      detail: summarizeTarget(item, band),
    };
  });
}

function assetPreview(asset?: AssetRecord | null) {
  if (!asset) {
    return "还没有新的正式记录。";
  }
  if (typeof asset.payload.summary === "string") {
    return compactText(asset.payload.summary, 120);
  }
  if (typeof asset.payload.owner_summary === "string") {
    return compactText(asset.payload.owner_summary, 120);
  }
  if (typeof asset.payload.portfolio_thesis === "string") {
    return `策略判断：${compactText(asset.payload.portfolio_thesis, 88)}`;
  }
  if (Array.isArray(asset.payload.decisions)) {
    return summarizeDecisionList(asset.payload.decisions);
  }
  if (typeof asset.payload.message === "string") {
    return asset.payload.message;
  }
  if (typeof asset.payload.category === "string" && typeof asset.payload.summary === "string") {
    return `${newsCategoryLabel(asset.payload.category)}：${asset.payload.summary}`;
  }
  return "已生成结构化记录，详细链路会在系统归档中继续保留。";
}

function renderCollection<T>(
  items: T[],
  renderItem: (item: T, index: number) => ReactNode,
  emptyMessage: string,
) {
  if (items.length === 0) {
    return <EmptyState message={emptyMessage} />;
  }
  return items.map((item, index) => renderItem(item, index));
}

function renderAssetCollection(
  items: AssetRecord[],
  renderItem: (item: AssetRecord, index: number) => ReactNode,
  emptyMessage: string,
) {
  return renderCollection(items, renderItem, emptyMessage);
}

function riskStateLabel(riskOverlay: OverviewData["risk_overlay"]) {
  const state = String(riskOverlay?.state ?? "normal").toLowerCase();
  if (state === "exit") {
    return "退出保护";
  }
  if (state === "reduce") {
    return "减仓保护";
  }
  if (state === "observe") {
    return "观察区";
  }
  if (state === "fallback") {
    return "回撤线已加载";
  }
  return "风险正常";
}

function riskStateNarrative(riskOverlay: OverviewData["risk_overlay"], latestPortfolio: Record<string, unknown>) {
  if (!riskOverlay) {
    return `当前账户余额 ${usdCompactText(latestPortfolio["total_equity_usd"])}，但还没有取到正式风控覆盖层。`;
  }
  const current = usdCompactText(riskOverlay.current_equity_usd);
  const peak = usdCompactText(riskOverlay.day_peak_equity_usd);
  return `今日组合峰值 ${peak}，当前余额 ${current}。黄橙红三条线分别对应观察、减仓与退出。`;
}

function overviewExecutionSummary(records: AssetRecord[]) {
  if (records.length === 0) {
    return "最近还没有新的正式执行结果。";
  }
  const latest = records[0];
  const headline = tradeHeadline(latest);
  const amount = usdText(actualFilledNotional(latest) ?? latest.payload["notional_usd"]);
  return `${headline}，成交金额 ${amount}。点击展开可看完整回执。`;
}

function overviewEventSummary(records: AssetRecord[]) {
  if (records.length === 0) {
    return "当前还没有新的正式高优先事件。";
  }
  const latest = records[0];
  const impact = impactLabel(String(latest.payload["impact_level"] ?? "low"));
  const summary = nonEmptyText(latest.payload["summary"], "暂无摘要。");
  return `${impact}影响：${compactText(summary, 54)} 点击展开查看事件卡片。`;
}

function latestAssetTimestamp(data?: AgentLatestData) {
  const latest = data?.latest_asset?.created_at ?? data?.session?.last_active_at;
  if (typeof latest === "string" && latest.length > 0) {
    return formatTime(latest);
  }
  return "尚无记录";
}

function nonEmptyText(value: unknown, fallback: string) {
  if (typeof value === "string" && value.trim().length > 0) {
    return value.trim();
  }
  return fallback;
}

function readRechecks(strategy: Record<string, unknown>) {
  const raw = Array.isArray(strategy.scheduled_rechecks) ? strategy.scheduled_rechecks : [];
  return raw.slice(0, 6).map((item, index) => {
    const record = asRecord(item) ?? {};
    return {
      label: `复核 ${index + 1}`,
      detail: `${nonEmptyText(record.reason, "等待下一轮主线复核")} · ${nonEmptyText(record.recheck_at_utc, "时间未写入")}`,
    };
  });
}

function urgencyLabel(value: unknown) {
  const raw = String(value ?? "").toLowerCase();
  if (raw === "high") {
    return "高优先";
  }
  if (raw === "medium") {
    return "中优先";
  }
  if (raw === "low") {
    return "低优先";
  }
  return "常规";
}

function executionThoughtResultText(result: Record<string, unknown>) {
  if (result.success === true) {
    return `后来执行成功，成交金额 ${usdText(result.notional_usd)}。`;
  }
  if (typeof result.message === "string" && result.message.trim().length > 0) {
    return compactText(result.message, 90);
  }
  if (result.technical_failure === true) {
    return "后来遇到技术性失败，系统已留下回执。";
  }
  return "后来没有形成明确的执行回执。";
}

/* readChiefLearnings has been replaced by inline logic in ChiefRetroTimeline */

function impactTone(impact: string) {
  if (impact === "high") {
    return "text-ember";
  }
  if (impact === "medium") {
    return "text-signal";
  }
  return "text-neon";
}

function shortId(value: string) {
  return value.length > 12 ? `${value.slice(0, 10)}...` : value;
}

function formatTime(value: string) {
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

function formatBalanceLabel(value: number, granularity: "15m" | "1h" | "1d") {
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

function connectionStateLabel(state: string, streamDisabled = false) {
  if (streamDisabled) {
    return "半实时轮询";
  }
  if (state === "open") {
    return "已连接";
  }
  if (state === "error") {
    return "异常";
  }
  return "连接中";
}

function streamBadgeTone(state: string, streamDisabled = false) {
  if (streamDisabled) {
    return "text-amber-200";
  }
  if (state === "open") {
    return "text-neon";
  }
  if (state === "error") {
    return "text-red-300";
  }
  return "text-signal";
}

function strategyBadgeValue(strategy: Record<string, unknown>) {
  const revision = strategyRevision(strategy);
  if (revision) {
    return `第 ${revision} 版`;
  }
  if (typeof strategy["strategy_id"] === "string" && strategy["strategy_id"].length > 0) {
    return "已就绪";
  }
  return "待生成";
}

function balanceWindowLabel(granularity: BalanceGranularity) {
  if (granularity === "15m") {
    return "15 分钟";
  }
  if (granularity === "1h") {
    return "1 小时";
  }
  return "日线";
}

function balanceGranularityMs(granularity: BalanceGranularity) {
  if (granularity === "15m") {
    return 15 * 60 * 1000;
  }
  if (granularity === "1h") {
    return 60 * 60 * 1000;
  }
  return 24 * 60 * 60 * 1000;
}

function balanceBucketCount(granularity: BalanceGranularity) {
  if (granularity === "15m") {
    return 96; // 24 hours
  }
  if (granularity === "1h") {
    return 168; // 7 days
  }
  return 30; // 30 days (matches backend daily lookback)
}

function strategyIdentity(strategy: Record<string, unknown>) {
  const revision = strategyRevision(strategy);
  const strategyId = typeof strategy["strategy_id"] === "string" ? shortId(strategy["strategy_id"]) : "待生成";
  return revision ? `第 ${revision} 版 · ${strategyId}` : strategyId;
}

function balanceNarrative(
  latestPortfolio: Record<string, unknown>,
  granularity: BalanceGranularity,
  points: Array<{ equity: number }>,
) {
  if (points.length === 0) {
    return "当前还没有足够多的组合快照，等后续 runtime pull 和执行结果累积后，这里会自动长出余额曲线。";
  }
  const first = points[0];
  const last = points[points.length - 1];
  const delta = last.equity - first.equity;
  const exposure = nominalMarginPctLabel(latestPortfolio["total_exposure_usd"], latestPortfolio);
  const direction = delta > 0 ? "上升" : delta < 0 ? "回落" : "基本持平";
  return `${balanceWindowLabel(granularity)}视角下，横轴已经按固定粒度重排。账户余额目前约 ${usdCompactText(last.equity)}，相较窗口起点 ${direction} ${usdCompactText(
    Math.abs(delta),
  )}。当前总敞口约占名义保证金 ${exposure}。`;
}

function strategyRevision(strategy: Record<string, unknown>) {
  const raw = strategy["revision_number"];
  if (typeof raw === "number") {
    return raw;
  }
  if (typeof raw === "string" && raw.length > 0) {
    return raw;
  }
  return null;
}

function portfolioModeLabel(value: unknown) {
  const mode = String(value ?? "idle");
  if (mode === "defensive") {
    return "防守";
  }
  if (mode === "normal") {
    return "常规";
  }
  if (mode === "aggressive") {
    return "进攻";
  }
  if (mode === "idle") {
    return "空闲";
  }
  return mode;
}

function rtPortfolioPostureLabel(value: unknown, fallbackMode: unknown) {
  const posture = String(value ?? "").trim().toLowerCase();
  if (!posture) {
    return `${portfolioModeLabel(fallbackMode)}节奏`;
  }
  if (posture === "normal_staged_build") {
    return "常规推进，分批建仓";
  }
  if (posture === "flat") {
    return "轻仓或空仓，先不主动加风险";
  }
  if (posture === "staged-accumulation") {
    return "顺着主线，分批加仓";
  }
  if (posture === "reduce_only") {
    return "先减风险，不做新的进攻";
  }
  return posture.replace(/[_-]+/g, " ");
}

function rtWorkingPostureLabel(value: unknown) {
  const posture = String(value ?? "").trim().toLowerCase();
  if (posture === "staged-accumulation") {
    return "分批加仓";
  }
  if (posture === "priority-reduce" || posture === "reduce-first") {
    return "优先减仓";
  }
  if (posture === "flat-watch") {
    return "继续观察";
  }
  if (posture === "hold-core") {
    return "保留核心仓";
  }
  if (posture === "neutral-hold") {
    return "维持现状";
  }
  if (posture === "watch") {
    return "继续观察";
  }
  if (posture) {
    return posture.replace(/[_-]+/g, " ");
  }
  return "暂无姿态";
}

function rtWorkingPostureTone(value: unknown) {
  const posture = String(value ?? "").trim().toLowerCase();
  if (posture.includes("reduce")) {
    return "border border-orange-300/20 bg-orange-300/10 text-orange-100";
  }
  if (posture.includes("accum") || posture.includes("add") || posture.includes("build")) {
    return "border border-emerald-300/20 bg-emerald-300/10 text-emerald-100";
  }
  if (posture.includes("watch") || posture.includes("flat")) {
    return "border border-slate-300/20 bg-slate-300/10 text-slate-100";
  }
  return "border border-white/10 bg-white/[0.06] text-slate-100";
}

function rtDeskHeadline(brief: Record<string, unknown> | null, latestStrategy: Record<string, unknown>) {
  const deskFocus = typeof brief?.desk_focus === "string" ? brief.desk_focus : "";
  if (deskFocus) {
    return compactText(deskFocus, 160);
  }
  const mode = portfolioModeLabel(latestStrategy["portfolio_mode"]);
  return `RT 还没写出完整地图，先按 ${mode} 节奏观察最新执行与风险变化。`;
}

function rtNoviceGuide(brief: Record<string, unknown> | null, latestStrategy: Record<string, unknown>) {
  const posture = rtPortfolioPostureLabel(brief?.portfolio_posture, latestStrategy["portfolio_mode"]);
  const risk = rtRiskBiasLabel(brief?.risk_bias);
  return `当前整体以${posture}为主。下方 3 张卡分别写清 BTC、ETH、SOL 现在更偏向加仓、减仓还是继续观察；如果市场走坏，先按“${compactText(risk, 30)}”这一条执行。`;
}

function rtMetadataPills(brief: Record<string, unknown> | null, trigger: Record<string, unknown> | null) {
  const items: string[] = [];
  const strategyKey = typeof brief?.strategy_key === "string" ? brief.strategy_key : "";
  const refreshReason = typeof brief?.map_refresh_reason === "string" ? brief.map_refresh_reason : "";
  const triggerReason = typeof trigger?.reason === "string" ? trigger.reason : "";
  const triggerCoins = Array.isArray(trigger?.coins) ? trigger.coins.filter(Boolean).slice(0, 3) : [];

  if (strategyKey) {
    items.push(`基于 ${rtStrategyKeyLabel(strategyKey)}`);
  }
  if (refreshReason) {
    items.push(`地图刷新：${rtRefreshReasonLabel(refreshReason)}`);
  }
  if (triggerReason) {
    items.push(`触发原因：${rtRefreshReasonLabel(triggerReason)}`);
  }
  if (typeof trigger?.lock_mode === "string" && trigger.lock_mode) {
    items.push(`风险锁：${rtRefreshReasonLabel(trigger.lock_mode)}`);
  }
  if (triggerCoins.length) {
    items.push(`关注：${triggerCoins.map((coin) => String(coin).toUpperCase()).join(" / ")}`);
  }
  return items;
}

function rtStrategyKeyLabel(value: string) {
  const revision = value.match(/:r(\d+)$/);
  if (revision) {
    return `策略 r${revision[1]}`;
  }
  return compactText(value, 20);
}

function rtRefreshReasonLabel(value: string) {
  const normalized = value.trim().toLowerCase();
  const labels: Record<string, string> = {
    pm_strategy_revision: "PM 更新策略后重排",
    execution_followup: "执行后跟进",
    cadence: "班次巡检",
    condition_trigger: "条件触发",
    headline_risk: "事件冲击",
    reduce_only: "只减仓",
    flat_only: "只平仓",
  };
  return labels[normalized] ?? value.replace(/[_-]+/g, " ");
}

function rtRiskBiasLabel(value: unknown) {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (!normalized) {
    return "风险状态正常。";
  }
  const labels: Record<string, string> = {
    opportunistic_with_hedges: "机会优先，但保留对冲和回撤保护",
    normal: "风险状态正常，可按策略推进",
    neutral: "风险状态正常，可按策略推进",
    defensive: "偏防守，先控回撤",
    reduce_only: "只减仓，不开新风险",
    flat_only: "只平仓，暂不持新仓",
    risk_on: "可以主动承担风险",
    risk_off: "优先收缩风险",
  };
  return labels[normalized] ?? normalized.replace(/[_-]+/g, " ");
}

function strategyFocusText(strategy: Record<string, unknown>) {
  const thesis = typeof strategy["portfolio_thesis"] === "string" ? strategy["portfolio_thesis"] : "";
  if (!thesis) {
    return "PM 还没有正式提交策略。";
  }
  return compactText(thesis, 96);
}

function directionLabel(value: unknown) {
  const direction = String(value ?? "flat");
  if (direction === "long") {
    return "做多";
  }
  if (direction === "short") {
    return "做空";
  }
  return "观望";
}

function stateLabel(value: unknown) {
  const state = String(value ?? "watch");
  if (state === "active") {
    return "主动跟踪";
  }
  if (state === "watch") {
    return "观察";
  }
  if (state === "disabled") {
    return "停用";
  }
  return state;
}

function summarizeTarget(item: Record<string, unknown>, band: unknown[]) {
  const min = formatBandValue(band[0]);
  const max = formatBandValue(band[1]);
  const discretion = formatPct(item.rt_discretion_band_pct);
  return `${stateLabel(item.state)}，目标敞口 ${min} 到 ${max}。RT 机动额度 ${discretion}。`;
}

function formatBandValue(value: unknown) {
  const number = toNumber(value);
  return number === null ? "0%" : `${trimNumber(number)}%`;
}

type ExposurePill = {
  coin: string;
  direction?: string;
  directionTone?: "long" | "short" | "flat" | "muted";
  exposure: string;
  strategyExposure?: string;
  share: string;
  strategyShare?: string;
};

function buildNominalExposurePills(
  latestPortfolio: Record<string, unknown>,
  latestStrategy: Record<string, unknown>,
): ExposurePill[] {
  const positions = Array.isArray(latestPortfolio["positions"]) ? latestPortfolio["positions"] : [];
  const positionMap = new Map(
    positions
      .map((position) => asRecord(position))
      .filter((position): position is Record<string, unknown> => position !== null)
      .map((position) => [String(position.coin ?? "").toUpperCase(), position]),
  );

  const targets = Array.isArray(latestStrategy["targets"]) ? latestStrategy["targets"] : [];
  const targetMap = new Map(
    targets
      .map((target) => asRecord(target))
      .filter((target): target is Record<string, unknown> => target !== null)
      .map((target) => [String(target.symbol ?? "").toUpperCase(), target]),
  );

  return [
    ...["BTC", "ETH", "SOL"].map<ExposurePill>((coin) => {
      const position = positionMap.get(coin);
      const target = targetMap.get(coin);
      const { label: direction, tone } = positionDirectionLabel(position, target);
      return {
        coin,
        direction,
        directionTone: tone,
        exposure: positionNotionalLabel(position),
        strategyExposure: targetExposureLabel(target, latestPortfolio),
        share: nominalMarginPctLabel(positionNotionalValue(position), latestPortfolio),
        strategyShare: targetSharePctLabel(target),
      };
    }),
    {
      coin: "总敞口",
      exposure: usdCompactText(latestPortfolio["total_exposure_usd"]),
      share: nominalMarginPctLabel(latestPortfolio["total_exposure_usd"], latestPortfolio),
    },
  ];
}

function positionDirectionLabel(
  position?: Record<string, unknown>,
  target?: Record<string, unknown>,
): { label: string; tone: "long" | "short" | "flat" | "muted" } {
  const side = position ? String(position.side ?? "").toLowerCase() : "";
  if (side === "long") {
    return { label: "做多", tone: "long" };
  }
  if (side === "short") {
    return { label: "做空", tone: "short" };
  }
  const targetDirection = target ? String(target.direction ?? "").toLowerCase() : "";
  if (targetDirection === "long") {
    return { label: "待做多", tone: "muted" };
  }
  if (targetDirection === "short") {
    return { label: "待做空", tone: "muted" };
  }
  if (targetDirection === "flat") {
    return { label: "观望", tone: "flat" };
  }
  return { label: "空仓", tone: "muted" };
}

function positionNotionalLabel(position?: Record<string, unknown>) {
  if (!position) {
    return "$0";
  }
  const notional = toNumber(position.notional_usd) ?? toNumber(position.current_notional_usd);
  if (notional === null) {
    return "$0";
  }
  return usdCompactText(notional);
}

function positionNotionalValue(position?: Record<string, unknown>) {
  if (!position) {
    return 0;
  }
  return toNumber(position.notional_usd) ?? toNumber(position.current_notional_usd) ?? 0;
}

function targetExposureBandTop(target?: Record<string, unknown>): number | null {
  if (!target) {
    return null;
  }
  const band = Array.isArray(target.target_exposure_band_pct) ? target.target_exposure_band_pct : null;
  if (!band || band.length < 2) {
    return null;
  }
  return toNumber(band[1]);
}

function displayEquityBudget(latestPortfolio: Record<string, unknown>) {
  return toNumber(latestPortfolio["total_equity_usd"]) ?? DEFAULT_DISPLAY_EQUITY_USD;
}

function displayNominalBudget(latestPortfolio: Record<string, unknown>) {
  return displayEquityBudget(latestPortfolio) * DISPLAY_LEVERAGE;
}

function targetExposureLabel(target: Record<string, unknown> | undefined, latestPortfolio: Record<string, unknown>): string | undefined {
  const topPct = targetExposureBandTop(target);
  if (topPct === null) {
    return undefined;
  }
  const usd = (displayNominalBudget(latestPortfolio) * topPct) / 100;
  return usdCompactText(usd);
}

function targetSharePctLabel(target?: Record<string, unknown>): string | undefined {
  const topPct = targetExposureBandTop(target);
  if (topPct === null) {
    return undefined;
  }
  return `${trimNumber(topPct)}%`;
}

function configuredLeverageLabel(latestPortfolio: Record<string, unknown>) {
  return `${DISPLAY_LEVERAGE}x（名义${usdCompactText(displayNominalBudget(latestPortfolio))}）`;
}

function nominalMarginPctLabel(value: unknown, latestPortfolio: Record<string, unknown>) {
  const notional = toNumber(value) ?? 0;
  const nominalBudget = displayNominalBudget(latestPortfolio);
  const pct = nominalBudget > 0 ? (notional / nominalBudget) * 100 : 0;
  return `名义占用 ${pct.toLocaleString("zh-CN", { minimumFractionDigits: pct === 0 ? 0 : 2, maximumFractionDigits: 2 })}%`;
}

function buildBalanceHistory(
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

function computeBalanceChartWidth(length: number, granularity: BalanceGranularity) {
  const minWidth = 520;
  const pointWidth = granularity === "15m" ? 22 : granularity === "1h" ? 28 : 48;
  return Math.max(minWidth, length * pointWidth);
}

function buildCandlePoints(
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

function formatCandleLabel(timestampMs: number, timeframe: KlineTimeframe): string {
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

function computeKlineChartWidth(length: number): number {
  const minWidth = 520;
  const pointWidth = 16;
  return Math.max(minWidth, length * pointWidth);
}

function buildKlinePriceDomain(candles: CandlePoint[]): [number, number] | [] {
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

function buildKlinePriceTicks(domain: [number, number] | []): number[] {
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

function balanceScrollCaption(length: number, granularity: BalanceGranularity) {
  if (length <= 1) {
    return "等待更多历史快照";
  }
  return `已同步 ${length} 个 ${balanceWindowLabel(granularity)}点。桌面滚轮浏览，移动端左右滑动，只有主图与时间轴会横向滚动。`;
}

function buildBalanceTicks(points: Array<{ equity: number }>) {
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

function balanceAxisTickLabel(value: number) {
  return `$${trimNumber(value)}`;
}

function buildBalanceDomain(points: Array<{ equity: number }>) {
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

function newerOverview(
  streamOverview: OverviewData | undefined,
  queryOverview: OverviewData | undefined,
) {
  if (!streamOverview) {
    return queryOverview;
  }
  if (!queryOverview) {
    return streamOverview;
  }
  return overviewTimestamp(queryOverview) >= overviewTimestamp(streamOverview) ? queryOverview : streamOverview;
}

function overviewTimestamp(overview: OverviewData) {
  const systemUpdatedAt = typeof overview.system?.updated_at === "string" ? overview.system.updated_at : null;
  const timestamp = systemUpdatedAt ? new Date(systemUpdatedAt).getTime() : Number.NaN;
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function executionRecordTitle(asset: AssetRecord) {
  return String(asset.payload["coin"] ?? asset.payload["symbol"] ?? "执行记录");
}

function tradeHeadline(asset: AssetRecord) {
  const coin = executionRecordTitle(asset);
  return `${tradeVerb(asset)} ${coin}`;
}

function tradeVerb(asset: AssetRecord) {
  const side = String(asset.payload["side"] ?? "").toLowerCase();
  const action = String(asset.payload["action"] ?? "").toLowerCase();
  if (action === "reduce" || action === "close") {
    if (side === "long") {
      return "卖出";
    }
    if (side === "short") {
      return "买回";
    }
    return actionLabel(action);
  }
  if (action === "hold") {
    return "持有";
  }
  if (action === "wait") {
    return "观望";
  }
  if (side === "long") {
    return "买入";
  }
  if (side === "short") {
    return "卖空";
  }
  return actionLabel(action);
}

function executionRecordSuccess(asset: AssetRecord) {
  return Boolean(asset.payload["success"]);
}

function executionRecordStatus(asset: AssetRecord) {
  if (asset.payload["success"] === true) {
    return "已执行";
  }
  if (asset.payload["message"]) {
    return "未成交";
  }
  return "待观察";
}

function executionRecordSummary(asset: AssetRecord) {
  const action = actionLabel(asset.payload["action"]);
  const executedNotional = actualFilledNotional(asset);
  const amount = usdText(executedNotional ?? asset.payload["notional_usd"]);
  const price = priceText(asset.payload["fill_price"]);
  const message = typeof asset.payload["message"] === "string" ? asset.payload["message"] : null;
  if (message) {
    return message;
  }
  if (price) {
    return `${action}，成交金额约 ${amount}，成交价 ${price}。`;
  }
  return `${action}，金额约 ${amount}。`;
}

function executionRecordMeta(asset: AssetRecord) {
  const fills = Array.isArray(asset.payload["fills"]) ? asset.payload["fills"] : [];
  if (fills.length > 0) {
    return `已回传 ${fills.length} 笔成交回执。`;
  }
  if (asset.payload["technical_failure"] === true) {
    return "这次执行遇到技术问题，系统已记录失败原因。";
  }
  return "这条执行没有额外的公开回执。";
}

function tradeTimeLabel(asset: AssetRecord) {
  const fill = firstFill(asset);
  if (fill?.trade_time) {
    return `下单时间：${formatTime(fill.trade_time)}`;
  }
  if (typeof asset.payload["executed_at"] === "string") {
    return `执行时间：${formatTime(asset.payload["executed_at"])}`;
  }
  return `记录时间：${formatTime(asset.created_at)}`;
}

function firstFill(asset: AssetRecord) {
  const fills = Array.isArray(asset.payload["fills"]) ? asset.payload["fills"] : [];
  const first = asRecord(fills[0]);
  if (!first) {
    return null;
  }
  return {
    price: toNumber(first.price),
    size: typeof first.size === "string" ? first.size : null,
    trade_time: typeof first.trade_time === "string" ? first.trade_time : null,
  };
}

function actualFilledNotional(asset: AssetRecord) {
  const fills = Array.isArray(asset.payload["fills"]) ? asset.payload["fills"] : [];
  const total = fills.reduce((sum, fill) => {
    const record = asRecord(fill);
    const price = toNumber(record?.price);
    const size = toNumber(record?.size);
    if (price === null || size === null) {
      return sum;
    }
    return sum + price * size;
  }, 0);
  return total > 0 ? total : null;
}

function currentPositionLeverage(asset: AssetRecord, latestPortfolio: Record<string, unknown>) {
  const positions = Array.isArray(latestPortfolio["positions"]) ? latestPortfolio["positions"] : [];
  const coin = executionRecordTitle(asset);
  const match = positions
    .map((position) => asRecord(position))
    .find((position) => String(position?.coin ?? "") === coin);
  if (match?.leverage) {
    return `${match.leverage}x`;
  }
  return "未回传";
}

function actionLabel(value: unknown) {
  const action = String(value ?? "wait");
  if (action === "open") {
    return "开仓";
  }
  if (action === "add") {
    return "加仓";
  }
  if (action === "reduce") {
    return "减仓";
  }
  if (action === "close") {
    return "平仓";
  }
  if (action === "hold") {
    return "维持仓位";
  }
  return "等待";
}

function newsCategoryLabel(value: unknown) {
  const category = String(value ?? "macro");
  if (category === "macro") {
    return "宏观";
  }
  if (category === "policy") {
    return "政策";
  }
  if (category === "onchain") {
    return "链上";
  }
  return category;
}

function impactLabel(value: string) {
  if (value === "high") {
    return "高";
  }
  if (value === "medium") {
    return "中";
  }
  return "低";
}

function sessionStatusLabel(value: string) {
  if (value === "active") {
    return "在线";
  }
  if (value === "running") {
    return "执行中";
  }
  if (value === "idle") {
    return "空闲";
  }
  return "离线";
}

function assetTypeLabel(value: string) {
  const labels: Record<string, string> = {
    strategy: "策略",
    execution_batch: "执行批次",
    execution_result: "执行结果",
    macro_event: "宏观事件",
    macro_daily_memory: "宏观日记忆",
    chief_retro: "Chief 复盘",
    rt_tactical_map: "RT 战术地图",
    owner_summary: "Owner 汇报",
    learning: "学习记录",
    portfolio_snapshot: "组合快照",
  };
  return labels[value] ?? value;
}

function summarizeEvent(event: EventEnvelope) {
  const eventType = event.event_type;
  const payload = event.payload;
  if (eventType === "strategy.submitted") {
    return {
      title: "PM 提交了新策略",
      detail: "新的策略版本已经正式落地。",
    };
  }
  if (eventType === "execution.submitted") {
    return {
      title: "RT 提交了执行决策",
      detail: "新的执行批次已经送审。",
    };
  }
  if (eventType === "execution.result.completed") {
    return {
      title: "交易网关返回了执行结果",
      detail: typeof payload["message"] === "string" ? payload["message"] : "执行结果已经写回系统。",
    };
  }
  if (eventType === "workflow.state.completed") {
    return {
      title: "流程完成",
      detail: "这条链路已经正常走完。",
    };
  }
  if (eventType === "workflow.state.degraded") {
    return {
      title: "流程降级",
      detail: "链路完成了部分步骤，但过程中出现了问题。",
    };
  }
  if (eventType === "notification.sent") {
    return {
      title: "通知已发出",
      detail: "重要结果已经推送给对应接收方。",
    };
  }
  return {
    title: humanizeToken(eventType),
    detail: `${moduleLabels[event.source_module] ?? event.source_module} 发出了一条正式事件。`,
  };
}

function humanizeToken(value: string) {
  return value
    .split(/[._]/g)
    .filter(Boolean)
    .join(" ");
}

function summarizeDecisionList(decisions: unknown[]) {
  if (decisions.length === 0) {
    return "本轮没有新增动作，维持现状。";
  }
  const first = asRecord(decisions[0]);
  if (!first) {
    return "已生成执行决策。";
  }
  const symbol = String(first.symbol ?? "组合");
  const action = actionLabel(first.action);
  const size = formatPct(first.size_pct_of_equity);
  return `${symbol}：${action}，计划使用 ${size} 的预算。`;
}

function usdText(value: unknown) {
  const number = toNumber(value);
  if (number === null) {
    return "0 美元";
  }
  return `${trimNumber(number)} 美元`;
}

function usdCompactText(value: unknown) {
  const number = toNumber(value);
  if (number === null) {
    return "--";
  }
  return `$${trimNumber(number)}`;
}

function priceText(value: unknown) {
  const number = toNumber(value);
  if (number === null) {
    return null;
  }
  return `$${trimNumber(number)}`;
}

function formatPct(value: unknown) {
  const number = toNumber(value);
  if (number === null) {
    return "0%";
  }
  return `${trimNumber(number)}%`;
}

function trimNumber(value: number) {
  return value.toLocaleString("zh-CN", {
    maximumFractionDigits: value >= 100 ? 2 : 4,
  });
}

function compactText(value: string, maxLength: number) {
  const normalized = value.replace(/\s+/g, " ").trim();
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, Math.max(0, maxLength - 1)).trimEnd()}…`;
}

function normalizeRetroChallengePrompts(value: unknown): Array<{ label: string | null; text: string }> {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((item) => {
    if (typeof item === "string" && item.trim().length > 0) {
      return [{ label: null, text: item.trim() }];
    }
    const record = asRecord(item);
    if (!record) {
      return [];
    }
    const text = nonEmptyText(record.prompt ?? record.question ?? record.text, "");
    if (!text) {
      return [];
    }
    const role = typeof record.role === "string" ? record.role.trim() : "";
    return [{ label: role ? (ROLE_LABEL[role] ?? role) : null, text }];
  });
}

function stripLeadingOrdinal(value: string) {
  return value.replace(/^\s*\d+\.\s*/, "").trim();
}

function parseRoleJudgement(value: unknown): { grade: string | null; comment: string } {
  const record = asRecord(value);
  const explicitGrade = record ? nonEmptyText(record.grade, "") : "";
  const explicitComment = record ? nonEmptyText(record.comment ?? record.summary, "") : "";
  if (explicitGrade) {
    return {
      grade: explicitGrade,
      comment: explicitComment,
    };
  }
  const raw = nonEmptyText(value, "");
  const match = raw.match(/^(A[+-]?|B[+-]?|C[+-]?|D[+-]?|F)\s*(?:\|\s*(.+))?$/);
  if (match) {
    return {
      grade: match[1],
      comment: (match[2] ?? "").trim(),
    };
  }
  return {
    grade: null,
    comment: raw,
  };
}

function chiefRetroModeLabel(roundCount: unknown) {
  const count = toNumber(roundCount);
  if (count === null) {
    return "异步 briefs";
  }
  return `同步 ${Math.trunc(count)} 轮`;
}

function hasTextualLearningSection(ownerSummary: string) {
  return /学习指令|学习落实|学习结果|会后学习/.test(ownerSummary);
}

function chiefLearningChainState(props: {
  ownerSummary: string;
  directives: Array<Record<string, unknown>>;
  learningResults: Array<Record<string, unknown>>;
  learningCompleted: boolean;
}) {
  if (props.learningResults.length > 0) {
    return {
      value: props.learningCompleted ? "已回写" : "部分回写",
      tone: props.learningCompleted ? "text-emerald-300" : "text-sky-300",
    };
  }
  if (props.directives.length > 0) {
    return {
      value: "待落实",
      tone: "text-amber-300",
    };
  }
  if (hasTextualLearningSection(props.ownerSummary)) {
    return {
      value: "仅文本提及",
      tone: "text-amber-300",
    };
  }
  if (props.learningCompleted) {
    return {
      value: "已完成",
      tone: "text-emerald-300",
    };
  }
  return {
    value: "未结构化提交",
    tone: "text-slate-200",
  };
}

function toNumber(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim().length > 0) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function asRecord(value: unknown) {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function countActiveAgents(sessions: Array<Record<string, unknown>>) {
  return sessions.reduce((count, session) => {
    return String(session.status ?? "offline") === "active" ? count + 1 : count;
  }, 0);
}
