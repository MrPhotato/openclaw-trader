import type { AgentLatestData, ExecutionsData, MarketContextData, NewsData, OverviewData, ReplayData, StreamPayload } from "./types";

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`request_failed:${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchOverview() {
  return fetchJson<OverviewData>("/api/query/overview");
}

export function fetchNews() {
  return fetchJson<NewsData>("/api/query/news/current");
}

export function fetchExecutions() {
  return fetchJson<ExecutionsData>("/api/query/executions/recent");
}

export function fetchMarketContext() {
  return fetchJson<MarketContextData>("/api/query/market/context");
}

export function fetchAgentLatest(agentRole: string) {
  return fetchJson<AgentLatestData>(`/api/query/agents/${agentRole}/latest`);
}

export function fetchReplay(traceId?: string, module?: string) {
  const params = new URLSearchParams();
  if (traceId) {
    params.set("trace_id", traceId);
  }
  if (module) {
    params.set("module", module);
  }
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return fetchJson<ReplayData>(`/api/query/replay${suffix}`);
}

export function openEventStream(
  onMessage: (payload: StreamPayload) => void,
  onStateChange: (state: "open" | "closed" | "error") => void,
) {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host || "127.0.0.1:8788";
  const socket = new WebSocket(`${protocol}://${host}/api/stream/events`);
  socket.onopen = () => onStateChange("open");
  socket.onclose = () => onStateChange("closed");
  socket.onerror = () => onStateChange("error");
  socket.onmessage = (event) => {
    onMessage(JSON.parse(event.data) as StreamPayload);
  };
  return () => socket.close();
}
