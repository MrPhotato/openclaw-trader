import { useEffect, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";

import {
  fetchAgentLatest,
  fetchExecutions,
  fetchMarketContext,
  fetchNews,
  fetchOverview,
  openEventStream,
} from "./lib/api";
import { useMissionControlStore } from "./lib/store";
import type { AgentLatestData } from "./lib/types";
import {
  countActiveAgents,
  newerOverview,
  strategyBadgeValue,
  type BalanceGranularity,
} from "./lib/format";
import { agentPages, navItems } from "./features/agents/config";
import { Shell } from "./components/layout/Shell";
import type { StatusDotTone } from "./components/primitives/StatusDot";
import { OverviewView } from "./features/overview/OverviewView";
import { PmView } from "./features/pm/PmView";
import { RtView } from "./features/rt/RtView";
import { MeaView } from "./features/mea/MeaView";
import { ChiefView } from "./features/chief/ChiefView";

export default function App() {
  const [balanceGranularity, setBalanceGranularity] = useState<BalanceGranularity>("1h");
  const activeView = useMissionControlStore((state) => state.activeView);
  const connectionState = useMissionControlStore((state) => state.connectionState);
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
  const latestStrategy = overview?.latest_strategy?.payload ?? {};
  const latestPortfolio = overview?.latest_portfolio?.payload ?? {};

  const executionRecords = (
    executionsQuery.data?.results ?? overview?.recent_execution_results ?? []
  ).slice(0, 8);
  const macroEventRecords = (
    newsQuery.data?.macro_events ?? overview?.current_macro_events ?? []
  ).slice(0, 6);

  const agentDataByRole = Object.fromEntries(
    agentPages.map((agent, index) => [agent.role, agentQueries[index].data]),
  ) as Record<string, AgentLatestData | undefined>;
  const pmData = agentDataByRole.pm;
  const rtData = agentDataByRole.risk_trader;
  const meaData = agentDataByRole.macro_event_analyst;
  const chiefData = agentDataByRole.crypto_chief;

  const activeLabel = navItems.find((item) => item.key === activeView)?.label ?? "总览";

  // "Connected" means data is flowing by ANY means — live WebSocket open, or
  // REST has returned fresh data recently (covers remote-hosted / cloud-
  // forwarded setups where WS handshake can't make it through).
  const FRESH_DATA_WINDOW_MS = 45_000; // ~3× the 15s poll interval
  const now = Date.now();
  const restFresh =
    overviewQuery.isSuccess &&
    overviewQuery.dataUpdatedAt > 0 &&
    now - overviewQuery.dataUpdatedAt < FRESH_DATA_WINDOW_MS;
  const restBroken =
    overviewQuery.isError &&
    (overviewQuery.errorUpdatedAt ?? 0) > overviewQuery.dataUpdatedAt;

  const effectiveConnection: "open" | "error" | "closed" =
    connectionState === "open" || restFresh
      ? "open"
      : connectionState === "error" || restBroken
        ? "error"
        : "closed";

  const connectionLabel =
    effectiveConnection === "open"
      ? "已连接"
      : effectiveConnection === "error"
        ? "异常"
        : "连接中";
  const connectionDotTone: StatusDotTone =
    effectiveConnection === "open"
      ? "online"
      : effectiveConnection === "error"
        ? "error"
        : "warning";

  return (
    <Shell
      activeView={activeView}
      activeViewLabel={activeLabel}
      onSelect={setView}
      connectionLabel={connectionLabel}
      connectionDotTone={connectionDotTone}
      strategyValue={strategyBadgeValue(latestStrategy)}
      activeAgents={countActiveAgents(overview?.agent_sessions ?? [])}
    >
      {activeView === "overview" && (
        <OverviewView
          overview={overview}
          latestPortfolio={latestPortfolio}
          latestStrategy={latestStrategy}
          agentDataByRole={agentDataByRole}
          marketContext={marketContextQuery.data}
          executionRecords={executionRecords}
          macroEventRecords={macroEventRecords}
          balanceGranularity={balanceGranularity}
          onBalanceGranularityChange={setBalanceGranularity}
        />
      )}
      {activeView === "pm" && <PmView data={pmData} latestStrategy={latestStrategy} />}
      {activeView === "rt" && (
        <RtView
          data={rtData}
          latestStrategy={latestStrategy}
          latestPortfolio={latestPortfolio}
          overview={overview}
          executionResultsOverride={executionsQuery.data?.results}
        />
      )}
      {activeView === "mea" && <MeaView data={meaData} news={newsQuery.data} />}
      {activeView === "chief" && <ChiefView data={chiefData} agentDataByRole={agentDataByRole} />}
    </Shell>
  );
}
