import { useEffect, useRef, useState } from "react";
import type { ReactNode, TouchEvent as ReactTouchEvent, WheelEvent as ReactWheelEvent } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { fetchAgentLatest, fetchExecutions, fetchNews, fetchOverview, isStreamDisabled, openEventStream } from "./lib/api";
import { useMissionControlStore } from "./lib/store";
import type { AgentLatestData, AssetRecord, EventEnvelope, OverviewData, ViewKey } from "./lib/types";

const agentRoles = [
  { key: "pm", label: "PM", accent: "text-emerald-200" },
  { key: "risk_trader", label: "RT", accent: "text-orange-200" },
  { key: "macro_event_analyst", label: "MEA", accent: "text-sky-200" },
  { key: "crypto_chief", label: "Chief", accent: "text-amber-200" },
] as const;

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

const DISPLAY_PRINCIPAL_USD = 1000;
const DISPLAY_LEVERAGE = 5;
const DISPLAY_NOMINAL_USD = DISPLAY_PRINCIPAL_USD * DISPLAY_LEVERAGE;
type BalanceGranularity = "15m" | "1h" | "1d";
type BalancePoint = { label: string; equity: number; createdAtMs: number };
type BalanceViewport = { startIndex: number; endIndex: number };
type TouchGestureState = { x: number; y: number; viewport: BalanceViewport };

export default function App() {
  const [balanceGranularity, setBalanceGranularity] = useState<BalanceGranularity>("1h");
  const [balanceViewport, setBalanceViewport] = useState<BalanceViewport>({ startIndex: 0, endIndex: 0 });
  const touchGestureRef = useRef<TouchGestureState | null>(null);
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
    enabled: activeView === "overview" || activeView === "signals",
    refetchInterval: 30000,
  });
  const executionsQuery = useQuery({
    queryKey: ["executions"],
    queryFn: fetchExecutions,
    enabled: activeView === "overview" || activeView === "desk",
    refetchInterval: 15000,
  });
  const agentQueries = useQueries({
    queries: agentRoles.map((agent) => ({
      queryKey: ["agent", agent.key],
      queryFn: () => fetchAgentLatest(agent.key),
      enabled: activeView === "agents",
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
  const normalizedBalanceViewport = normalizeBalanceViewport(balanceViewport, balanceSeries.length, balanceGranularity);
  const visibleBalanceSeries = sliceBalanceSeries(balanceSeries, normalizedBalanceViewport);
  const balanceTicks = buildBalanceTicks(visibleBalanceSeries);
  const impactBreakdown = buildImpactBreakdown(newsQuery.data?.macro_events ?? []);

  useEffect(() => {
    setBalanceViewport(defaultBalanceViewport(balanceSeries.length, balanceGranularity));
  }, [balanceGranularity]);

  useEffect(() => {
    setBalanceViewport((current) => normalizeBalanceViewport(current, balanceSeries.length, balanceGranularity));
  }, [balanceGranularity, balanceSeries.length]);

  function handleBalanceWheel(event: ReactWheelEvent<HTMLDivElement>) {
    if (balanceSeries.length <= 1) {
      return;
    }
    event.preventDefault();
    const stepSize = Math.max(1, Math.round(Math.abs(event.deltaY) / 120));
    const deltaSteps = event.deltaY > 0 ? stepSize : -stepSize;
    setBalanceViewport((current) =>
      shiftBalanceViewport(
        normalizeBalanceViewport(current, balanceSeries.length, balanceGranularity),
        balanceSeries.length,
        deltaSteps,
        balanceGranularity,
      ),
    );
  }

  function handleBalanceTouchStart(event: ReactTouchEvent<HTMLDivElement>) {
    if (event.touches.length !== 1) {
      touchGestureRef.current = null;
      return;
    }
    const touch = event.touches[0];
    touchGestureRef.current = {
      x: touch.clientX,
      y: touch.clientY,
      viewport: normalizedBalanceViewport,
    };
  }

  function handleBalanceTouchMove(event: ReactTouchEvent<HTMLDivElement>) {
    const gesture = touchGestureRef.current;
    if (!gesture || event.touches.length !== 1 || balanceSeries.length <= 1) {
      return;
    }
    const touch = event.touches[0];
    const deltaX = touch.clientX - gesture.x;
    const deltaY = touch.clientY - gesture.y;
    if (Math.abs(deltaX) <= Math.abs(deltaY)) {
      return;
    }
    const stepSize = Math.trunc(deltaX / 24);
    if (stepSize === 0) {
      return;
    }
    event.preventDefault();
    const nextViewport = shiftBalanceViewport(
      gesture.viewport,
      balanceSeries.length,
      -stepSize,
      balanceGranularity,
    );
    touchGestureRef.current = {
      x: touch.clientX,
      y: touch.clientY,
      viewport: nextViewport,
    };
    setBalanceViewport(nextViewport);
  }

  function clearBalanceTouchGesture() {
    touchGestureRef.current = null;
  }

  return (
    <div className="min-h-screen bg-command-grid bg-[size:160px_160px,24px_24px,24px_24px] text-slate-100">
      <div className="mx-auto flex min-h-screen max-w-7xl flex-col gap-6 px-4 py-4 sm:px-6 lg:px-8">
        <header className="glass-panel rounded-[28px] px-6 py-5 shadow-glow">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
            <div className="space-y-2">
              <div className="flex items-center gap-3 text-xs uppercase tracking-[0.35em] text-ember">
                <span className="rounded-full border border-white/10 px-3 py-1 text-neon">OpenClaw</span>
                <span className="h-px w-16 animate-pulseLine bg-gradient-to-r from-neon via-white/30 to-transparent" />
                <span className="text-slate-400">公开看板</span>
              </div>
              <div>
                <h1 className="text-3xl font-semibold leading-none sm:text-5xl">交易指挥台</h1>
                <p className="mt-2 max-w-xl text-sm leading-6 text-slate-300 sm:text-base">
                  <span className="text-slate-200">openclaw-trader 是 OpenClaw 加密工作流背后的交易运行时，当前公开展示本金 $1000。</span>
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
            {[
              ["overview", "总览"],
              ["desk", "策略"],
              ["signals", "事件"],
              ["agents", "席位"],
            ].map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setView(key as ViewKey)}
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
          <section className="grid gap-6 lg:grid-cols-[1.35fr_0.95fr]" data-testid="overview-view">
            <div className="space-y-6">
              <Panel title="账户余额轨迹">
                <div className="mb-4 grid gap-3 sm:grid-cols-2">
                  <SummaryPill
                    label="账户余额（本金$1000）"
                    value={usdCompactText(latestPortfolio["total_equity_usd"])}
                  />
                  <SummaryPill
                    label="当前杠杆"
                    value={configuredLeverageLabel()}
                  />
                </div>
                <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  {buildNominalExposurePills(latestPortfolio).map((item) => (
                    <CoinExposurePill key={item.coin} coin={item.coin} exposure={item.exposure} share={item.share} />
                  ))}
                </div>
                <div
                  data-testid="balance-chart-viewport"
                  onWheel={handleBalanceWheel}
                  onTouchStart={handleBalanceTouchStart}
                  onTouchMove={handleBalanceTouchMove}
                  onTouchEnd={clearBalanceTouchGesture}
                  onTouchCancel={clearBalanceTouchGesture}
                  style={{ touchAction: "pan-y" }}
                >
                  <ChartShell>
                    <ResponsiveContainer width="100%" height={260}>
                      <LineChart data={visibleBalanceSeries}>
                        <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                        <XAxis
                          dataKey="label"
                          tick={{ fill: "#9fb0c7", fontSize: 12 }}
                          axisLine={false}
                          tickLine={false}
                          interval="preserveStartEnd"
                          minTickGap={28}
                        />
                        <YAxis
                          tick={{ fill: "#9fb0c7", fontSize: 12 }}
                          axisLine={false}
                          tickLine={false}
                          domain={["dataMin", "dataMax"]}
                          ticks={balanceTicks}
                          width={72}
                        />
                        <Tooltip
                          cursor={{ stroke: "rgba(113,246,209,0.35)" }}
                          formatter={(value: number) => [`$${trimNumber(value)}`, balanceWindowLabel(balanceGranularity)]}
                          labelFormatter={(label) => `时间：${label}`}
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
                    </ResponsiveContainer>
                  </ChartShell>
                </div>
                <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
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
                  <div className="text-xs text-slate-500" data-testid="balance-viewport-caption">
                    {balanceViewportCaption(balanceSeries, normalizedBalanceViewport, balanceGranularity)}
                  </div>
                </div>
                <div className="mt-3 text-sm text-slate-400">
                  {balanceNarrative(latestPortfolio, balanceGranularity, visibleBalanceSeries)}
                </div>
              </Panel>
            </div>
            <Panel title="下单动态">
              <div className="space-y-3">
                {(executionsQuery.data?.results ?? overview?.recent_execution_results ?? []).slice(0, 12).map((record) => (
                  <TradeBlotterCard key={record.asset_id} asset={record} latestPortfolio={latestPortfolio} />
                ))}
              </div>
            </Panel>
          </section>
        )}

        {activeView === "desk" && (
          <section className="grid gap-6 lg:grid-cols-[1.05fr_1fr]" data-testid="desk-view">
            <Panel title="PM 最新策略">
              <div className="space-y-4">
                <Headline label="策略版本" value={strategyIdentity(latestStrategy)} />
                <Headline label="组合模式" value={portfolioModeLabel(latestStrategy["portfolio_mode"])} />
                <Headline label="策略重点" value={strategyFocusText(latestStrategy)} />
                <Headline label="失效条件" value={String(latestStrategy["portfolio_invalidation"] ?? "暂无明确失效条件。")} />
                <div className="grid gap-3">
                  {readTargets(latestStrategy).map((target) => (
                    <div key={target.label} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                      <div className="flex items-center justify-between">
                        <span className="font-medium">{target.label}</span>
                        <span className="text-xs text-slate-400">{target.direction}</span>
                      </div>
                      <div className="mt-2 text-sm text-slate-300">{target.detail}</div>
                    </div>
                  ))}
                </div>
              </div>
            </Panel>
            <div className="space-y-6">
              <Panel title="最近执行">
                <div className="space-y-3">
                  {(executionsQuery.data?.results ?? overview?.recent_execution_results ?? []).slice(0, 10).map((record) => (
                    <div key={record.asset_id} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                      <div className="flex items-center justify-between">
                        <span className="font-medium">{executionRecordTitle(record)}</span>
                        <span className={executionRecordSuccess(record) ? "text-neon" : "text-red-300"}>
                          {executionRecordStatus(record)}
                        </span>
                      </div>
                      <div className="mt-2 text-sm text-slate-300">{executionRecordSummary(record)}</div>
                      <div className="mt-1 text-xs text-slate-500">{executionRecordMeta(record)}</div>
                    </div>
                  ))}
                </div>
              </Panel>
              <Panel title="链路内容">
                <div className="space-y-3">
                  {eventFeed.slice(0, 12).map((event) => (
                    <EventRow key={event.event_id} event={event} />
                  ))}
                </div>
              </Panel>
            </div>
          </section>
        )}

        {activeView === "signals" && (
          <section className="grid gap-6 lg:grid-cols-[1fr_1.1fr]" data-testid="signals-view">
            <Panel title="宏观影响分布">
              <ChartShell>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={impactBreakdown}>
                    <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                    <XAxis dataKey="impact" tick={{ fill: "#9fb0c7", fontSize: 12 }} axisLine={false} tickLine={false} />
                    <YAxis tick={{ fill: "#9fb0c7", fontSize: 12 }} axisLine={false} tickLine={false} />
                    <Tooltip cursor={{ fill: "rgba(255,255,255,0.04)" }} />
                    <Bar dataKey="count" radius={[8, 8, 0, 0]}>
                      {impactBreakdown.map((item) => (
                        <Cell key={item.impact} fill={item.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </ChartShell>
              <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-slate-300">
                {String(newsQuery.data?.macro_daily_memory?.payload?.["summary"] ?? "今天还没有形成正式的宏观日记忆。")}
              </div>
            </Panel>
            <Panel title="新闻看板">
              <div className="space-y-3">
                {(newsQuery.data?.macro_events ?? []).slice(0, 12).map((record) => (
                  <div key={record.asset_id} className="rounded-2xl border border-white/10 bg-white/5 p-4">
                    <div className="flex items-center justify-between">
                      <span className="font-medium">{newsCategoryLabel(record.payload["category"])}</span>
                      <span className={impactTone(String(record.payload["impact_level"] ?? "low"))}>
                        {impactLabel(String(record.payload["impact_level"] ?? "low"))}
                      </span>
                    </div>
                    <div className="mt-2 text-sm text-slate-300">{String(record.payload["summary"] ?? "No summary")}</div>
                  </div>
                ))}
              </div>
            </Panel>
          </section>
        )}

        {activeView === "agents" && (
          <section className="grid gap-6 lg:grid-cols-2" data-testid="agents-view">
            {agentRoles.map((agent, index) => (
              <AgentPanel
                key={agent.key}
                agent={agent}
                data={agentQueries[index].data}
              />
            ))}
          </section>
        )}
      </div>
    </div>
  );
}

function Panel(props: { title: string; children: ReactNode }) {
  return (
    <article className="glass-panel rounded-[28px] p-5 shadow-glow">
      <div className="mb-5">
        <h2 className="text-2xl font-semibold">{props.title}</h2>
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

function CoinExposurePill(props: { coin: string; exposure: string; share: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3">
      <div className="text-[10px] tracking-[0.2em] text-slate-500">{props.coin}</div>
      <div className="mt-1 text-base font-medium text-slate-200">{props.exposure}</div>
      <div className="mt-1 text-xs text-slate-400">{props.share}</div>
    </div>
  );
}

function ChartShell(props: { children: ReactNode }) {
  return <div className="rounded-[24px] border border-white/10 bg-white/5 p-3">{props.children}</div>;
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

function AgentPanel(props: {
  agent: { key: string; label: string; accent: string };
  data?: AgentLatestData;
}) {
  const sessionStatus = String(props.data?.session?.status ?? "offline");
  const latestType = String(props.data?.latest_asset?.asset_type ?? "none");

  return (
    <Panel title={props.agent.label}>
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
            <div className="text-[11px] tracking-[0.2em] text-slate-500">会话状态</div>
            <div className={`mt-3 text-xl font-semibold ${props.agent.accent}`}>{sessionStatusLabel(sessionStatus)}</div>
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/5 p-4">
            <div className="text-[11px] tracking-[0.2em] text-slate-500">最近产物</div>
            <div className="mt-3 text-xl font-semibold">{assetTypeLabel(latestType)}</div>
          </div>
        </div>
        <div className="space-y-3">
          {(props.data?.recent_assets ?? []).slice(0, 5).map((asset) => (
            <div key={asset.asset_id} className="rounded-2xl border border-white/10 bg-white/5 p-4">
              <div className="flex items-center justify-between">
                <span className="font-medium">{assetTypeLabel(asset.asset_type)}</span>
                <span className="text-xs text-slate-500">{formatTime(asset.created_at)}</span>
              </div>
              <div className="mt-2 text-sm text-slate-300">{assetPreview(asset)}</div>
            </div>
          ))}
        </div>
      </div>
    </Panel>
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

function assetPreview(asset: AssetRecord) {
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
    return 48;
  }
  if (granularity === "1h") {
    return 48;
  }
  return 7;
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
  const exposure = nominalMarginPctLabel(latestPortfolio["total_exposure_usd"]);
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

function buildNominalExposurePills(latestPortfolio: Record<string, unknown>) {
  const positions = Array.isArray(latestPortfolio["positions"]) ? latestPortfolio["positions"] : [];
  const positionMap = new Map(
    positions
      .map((position) => asRecord(position))
      .filter((position): position is Record<string, unknown> => position !== null)
      .map((position) => [String(position.coin ?? "").toUpperCase(), position]),
  );

  return [
    ...["BTC", "ETH", "SOL"].map((coin) => ({
      coin,
      exposure: positionNotionalLabel(positionMap.get(coin)),
      share: nominalMarginPctLabel(positionNotionalValue(positionMap.get(coin))),
    })),
    {
      coin: "总敞口",
      exposure: usdCompactText(latestPortfolio["total_exposure_usd"]),
      share: nominalMarginPctLabel(latestPortfolio["total_exposure_usd"]),
    },
  ];
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

function configuredLeverageLabel() {
  return `${DISPLAY_LEVERAGE}x（名义$${DISPLAY_NOMINAL_USD}）`;
}

function nominalMarginPctLabel(value: unknown) {
  const notional = toNumber(value) ?? 0;
  const pct = DISPLAY_NOMINAL_USD > 0 ? (notional / DISPLAY_NOMINAL_USD) * 100 : 0;
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
  let lastEquity: number | null = null;
  const series: BalancePoint[] = [];

  for (let bucketMs = startBucketMs; bucketMs <= endBucketMs; bucketMs += intervalMs) {
    const bucketEndMs = bucketMs + intervalMs - 1;
    while (pointIndex < seededPoints.length && seededPoints[pointIndex].createdAtMs <= bucketEndMs) {
      lastEquity = seededPoints[pointIndex].equity;
      pointIndex += 1;
    }

    if (lastEquity === null && rawPoints.length === 0 && fallbackEquity !== null) {
      lastEquity = fallbackEquity;
    }
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

function defaultBalanceViewport(length: number, granularity: BalanceGranularity): BalanceViewport {
  if (length <= 1) {
    return { startIndex: 0, endIndex: Math.max(0, length - 1) };
  }
  const visibleCount = Math.min(defaultVisiblePointCount(granularity), length);
  return {
    startIndex: Math.max(0, length - visibleCount),
    endIndex: length - 1,
  };
}

function normalizeBalanceViewport(
  viewport: BalanceViewport,
  length: number,
  granularity: BalanceGranularity,
): BalanceViewport {
  if (length <= 1) {
    return { startIndex: 0, endIndex: Math.max(0, length - 1) };
  }
  const safeStart = clampNumber(viewport.startIndex, 0, length - 1);
  const safeEnd = clampNumber(viewport.endIndex, safeStart, length - 1);
  if (safeEnd - safeStart + 1 < 2) {
    return defaultBalanceViewport(length, granularity);
  }
  return { startIndex: safeStart, endIndex: safeEnd };
}

function shiftBalanceViewport(
  viewport: BalanceViewport,
  length: number,
  deltaSteps: number,
  granularity: BalanceGranularity,
): BalanceViewport {
  if (length <= 1 || deltaSteps === 0) {
    return normalizeBalanceViewport(viewport, length, granularity);
  }
  const windowSize = Math.max(2, viewport.endIndex - viewport.startIndex + 1);
  const maxStart = Math.max(0, length - windowSize);
  const nextStart = clampNumber(viewport.startIndex + deltaSteps, 0, maxStart);
  return {
    startIndex: nextStart,
    endIndex: Math.min(length - 1, nextStart + windowSize - 1),
  };
}

function sliceBalanceSeries(points: BalancePoint[], viewport: BalanceViewport) {
  if (points.length === 0) {
    return [];
  }
  return points.slice(viewport.startIndex, viewport.endIndex + 1);
}

function defaultVisiblePointCount(granularity: BalanceGranularity) {
  if (granularity === "15m") {
    return 24;
  }
  if (granularity === "1h") {
    return 24;
  }
  return 7;
}

function balanceViewportCaption(
  points: BalancePoint[],
  viewport: BalanceViewport,
  granularity: BalanceGranularity,
) {
  if (points.length <= 1) {
    return "等待更多历史快照";
  }
  const start = points[viewport.startIndex]?.label ?? "--";
  const end = points[viewport.endIndex]?.label ?? "--";
  return `已同步 ${points.length} 个 ${balanceWindowLabel(granularity)}点，当前查看 ${start} 至 ${end}。桌面滚轮上下翻阅，手机左右滑动。`;
}

function buildBalanceTicks(points: Array<{ equity: number }>) {
  if (points.length === 0) {
    return [];
  }
  const values = points.map((point) => point.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  if (Math.abs(max - min) < 0.0001) {
    return [min];
  }

  const tickCount = 6;
  const step = (max - min) / (tickCount - 1);
  return Array.from({ length: tickCount }, (_, index) => Number((min + step * index).toFixed(4)));
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
  const orderId = typeof asset.payload["exchange_order_id"] === "string" ? shortId(asset.payload["exchange_order_id"]) : null;
  if (orderId) {
    return `订单号 ${orderId}`;
  }
  return "没有可展示的交易所订单号。";
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
      detail: payload["strategy_id"] ? `策略 ${shortId(String(payload["strategy_id"]))} 已写入系统。` : "新的策略版本已经正式落地。",
    };
  }
  if (eventType === "execution.submitted") {
    return {
      title: "RT 提交了执行决策",
      detail: payload["decision_id"] ? `执行批次 ${shortId(String(payload["decision_id"]))} 已提交。` : "新的执行批次已经送审。",
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

function clampNumber(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
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
