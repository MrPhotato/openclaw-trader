import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import App from "../app";
import { useMissionControlStore } from "../lib/store";

const overviewPayload = {
  system: { strategy_present: true, execution_present: true, updated_at: "2026-03-20T08:00:00Z" },
  latest_strategy: {
    asset_id: "strategy-1",
    asset_type: "strategy",
    payload: {
      strategy_id: "strategy_live",
      portfolio_mode: "normal",
      portfolio_thesis: "Momentum with capped risk.",
      targets: [{ symbol: "BTC", state: "active", direction: "long", target_exposure_band_pct: [1, 3], rt_discretion_band_pct: 1 }],
    },
    metadata: {},
    created_at: "2026-03-20T08:00:00Z",
  },
  latest_portfolio: {
    asset_id: "portfolio-1",
    asset_type: "portfolio_snapshot",
    payload: {
      total_equity_usd: "1002.5",
      available_equity_usd: "841.2",
      total_exposure_usd: "161.3",
    },
    metadata: {},
    created_at: "2026-03-20T08:00:00Z",
  },
  portfolio_history: [
    {
      created_at: "2026-03-20T07:30:00Z",
      total_equity_usd: "998.2",
    },
    {
      created_at: "2026-03-20T08:00:00Z",
      total_equity_usd: "1002.5",
    },
  ],
  latest_execution_batch: null,
  recent_execution_results: [],
  current_macro_events: [],
  agent_sessions: [],
  recent_notifications: [],
  recent_events: [
    {
      event_id: "evt-1",
      trace_id: "trace-1",
      source_module: "agent_gateway",
      event_type: "strategy.submitted",
      entity_type: "strategy",
      occurred_at: "2026-03-20T08:00:00Z",
      payload: {},
    },
  ],
};

const newsPayload = {
  latest_batch: null,
  macro_events: [
    {
      asset_id: "macro-1",
      asset_type: "macro_event",
      payload: { category: "macro", summary: "Fed headline", impact_level: "high" },
      metadata: {},
      created_at: "2026-03-20T08:05:00Z",
    },
  ],
  macro_daily_memory: null,
};

const executionPayload = {
  latest_execution_batch: null,
  results: [
    {
      asset_id: "execution-1",
      asset_type: "execution_result",
      payload: {
        coin: "BTC",
        action: "reduce",
        side: "long",
        success: true,
        notional_usd: "736.60",
        exchange_order_id: "order-1",
        fills: [
          {
            price: "68657.1",
            size: "0.0032",
            trade_time: "2026-03-22T11:16:15.650828Z",
          },
        ],
      },
      metadata: {},
      created_at: "2026-03-22T11:16:15.951502+00:00",
    },
  ],
};

const marketContextPayload = {
  market_context: {
    BTC: {
      compressed_price_series: {
        "15m": {
          points: [
            { timestamp: 1774150200, close: "70100" },
            { timestamp: 1774151100, close: "70220" },
          ],
          change_pct: 0.8,
        },
        "1h": {
          points: [
            { timestamp: 1774148400, close: "69880" },
            { timestamp: 1774152000, close: "70220" },
          ],
          change_pct: 1.1,
        },
        "24h": {
          points: [
            { timestamp: 1774065600, close: "69010" },
            { timestamp: 1774152000, close: "70220" },
          ],
          change_pct: 1.75,
        },
      },
      breakout_retest_state: { state: "range" },
      volatility_state: { state: "contracting" },
    },
  },
};

const agentPayload = {
  session: { status: "active" },
  latest_asset: null,
  recent_assets: [],
};

class MockWebSocket {
  static instances: MockWebSocket[] = [];

  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;

  constructor() {
    MockWebSocket.instances.push(this);
    queueMicrotask(() => this.onopen?.());
  }

  close() {
    this.onclose?.();
  }
}

describe("App", () => {
  beforeEach(() => {
    useMissionControlStore.setState({
      activeView: "overview",
      connectionState: "closed",
      liveEvents: [],
      streamOverview: undefined,
      replayFilters: {
        traceId: "",
        module: "",
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/query/overview")) {
          return Promise.resolve(new Response(JSON.stringify(overviewPayload)));
        }
        if (url.includes("/api/query/news/current")) {
          return Promise.resolve(new Response(JSON.stringify(newsPayload)));
        }
        if (url.includes("/api/query/executions/recent")) {
          return Promise.resolve(new Response(JSON.stringify(executionPayload)));
        }
        if (url.includes("/api/query/market/context")) {
          return Promise.resolve(new Response(JSON.stringify(marketContextPayload)));
        }
        if (url.includes("/api/query/replay")) {
          return Promise.resolve(new Response(JSON.stringify({ trace_id: null, events: [], states: [], render_hints: { mode: "timeline" } })));
        }
        if (url.includes("/api/query/agents/")) {
          return Promise.resolve(new Response(JSON.stringify(agentPayload)));
        }
        return Promise.resolve(new Response(JSON.stringify({})));
      }),
    );
    vi.stubGlobal("WebSocket", MockWebSocket as unknown as typeof WebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    MockWebSocket.instances = [];
  });

  test("renders dashboard and replay view", async () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByText("交易看板")).toBeInTheDocument());
    expect(screen.getByTestId("overview-view")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("卖出 BTC")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("交易方向：卖出")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("成交金额：219.7 美元")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("计划金额：736.6 美元")).toBeInTheDocument());

    fireEvent.click(screen.getByText("回放"));
    await waitFor(() => expect(screen.getByTestId("replay-view")).toBeInTheDocument());
  });

  test("switches balance granularity without crashing", async () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByText("账户余额轨迹")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "15 分钟" }));
    await waitFor(() => expect(screen.getByText(/15 分钟\s*视角下/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "日线" }));
    await waitFor(() => expect(screen.getByText(/日线\s*视角下/)).toBeInTheDocument());
  });
});
