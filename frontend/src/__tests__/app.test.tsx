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
      positions: [
        {
          coin: "BTC",
          position_share_pct_of_equity: 12.3,
          notional_usd: "161.3",
        },
      ],
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

  test("renders dashboard and switches between four views", async () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByText("交易指挥台")).toBeInTheDocument());
    expect(screen.getByTestId("overview-view")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("账户余额（本金$1000）")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("5x（名义$5000）")).toBeInTheDocument());
    expect(screen.queryByText("当前敞口")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("$161.3").length).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(screen.getAllByText("名义占用 3.23%").length).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(screen.getByText("ETH")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("SOL")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("总敞口")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByTestId("balance-viewport-caption")).toHaveTextContent("拖动下方时间窗可查看更早数据"));
    await waitFor(() => expect(screen.getByText("卖出 BTC")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("交易方向：卖出")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("成交金额：219.7 美元")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("计划金额：736.6 美元")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "策略" }));
    await waitFor(() => expect(screen.getByTestId("desk-view")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("策略重点")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "事件" }));
    await waitFor(() => expect(screen.getByTestId("signals-view")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "席位" }));
    await waitFor(() => expect(screen.getByTestId("agents-view")).toBeInTheDocument());
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

  test("prefers newer polled overview over stale stream overview", async () => {
    useMissionControlStore.setState({
      activeView: "overview",
      connectionState: "open",
      liveEvents: [],
      streamOverview: {
        ...overviewPayload,
        system: { ...overviewPayload.system, updated_at: "2026-03-20T07:00:00Z" },
        latest_portfolio: {
          ...overviewPayload.latest_portfolio,
          payload: {
            ...overviewPayload.latest_portfolio.payload,
            total_exposure_usd: "999.9",
            positions: [
              {
                coin: "BTC",
                notional_usd: "999.9",
              },
            ],
          },
        },
      },
    });

    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getAllByText("$161.3").length).toBeGreaterThanOrEqual(2));
    expect(screen.queryByText("$999.9")).not.toBeInTheDocument();
  });
});
