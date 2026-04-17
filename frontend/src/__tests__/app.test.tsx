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
      revision_number: 3,
      portfolio_mode: "normal",
      portfolio_thesis: "Momentum with capped risk and tighter execution discipline.",
      change_summary: "Raise BTC conviction and keep gross exposure capped.",
      flip_triggers: "If higher-timeframe structure fails together with a macro regime turn, flip instead of only trimming.",
      portfolio_invalidation: "If BTC loses structure and macro risk spikes, cut risk and re-check.",
      scheduled_rechecks: [{ recheck_at_utc: "2026-03-20T10:00:00Z", reason: "US session open" }],
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
  risk_overlay: {
    state: "observe",
    day_peak_equity_usd: "1030",
    current_equity_usd: "1002.5",
    observe: { drawdown_pct: 1.0, equity_usd: "1019.7" },
    reduce: { drawdown_pct: 2.0, equity_usd: "1009.4" },
    exit: { drawdown_pct: 3.0, equity_usd: "999.1" },
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
  agent_sessions: [
    { agent_role: "pm", status: "active" },
    { agent_role: "risk_trader", status: "active" },
  ],
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
      payload: { category: "macro", summary: "Fed headline turns risk sentiment colder.", impact_level: "high", source_refs: ["ref-1"] },
      metadata: {},
      created_at: "2026-03-20T08:05:00Z",
    },
    {
      asset_id: "macro-2",
      asset_type: "macro_event",
      payload: { category: "policy", summary: "SEC wording shifts the market toward defense.", impact_level: "high", source_refs: ["ref-2"] },
      metadata: {},
      created_at: "2026-03-20T08:08:00Z",
    },
    {
      asset_id: "macro-3",
      asset_type: "macro_event",
      payload: { category: "exchange", summary: "Exchange liquidity thins into Asia lunch.", impact_level: "medium", source_refs: ["ref-3"] },
      metadata: {},
      created_at: "2026-03-20T08:10:00Z",
    },
    {
      asset_id: "macro-4",
      asset_type: "macro_event",
      payload: { category: "macro", summary: "Dollar bid resumes and squeezes crypto beta.", impact_level: "high", source_refs: ["ref-4"] },
      metadata: {},
      created_at: "2026-03-20T08:12:00Z",
    },
  ],
  macro_daily_memory: {
    asset_id: "memory-1",
    asset_type: "macro_daily_memory",
    payload: { summary: "The market is trading around macro risk and headline sensitivity." },
    metadata: {},
    created_at: "2026-03-20T08:10:00Z",
  },
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
    {
      asset_id: "execution-2",
      asset_type: "execution_result",
      payload: {
        coin: "ETH",
        action: "add",
        side: "long",
        success: true,
        notional_usd: "418.40",
        exchange_order_id: "order-2",
        fills: [
          {
            price: "3520.4",
            size: "0.1189",
            trade_time: "2026-03-22T11:18:15.650828Z",
          },
        ],
      },
      metadata: {},
      created_at: "2026-03-22T11:18:15.951502+00:00",
    },
    {
      asset_id: "execution-3",
      asset_type: "execution_result",
      payload: {
        coin: "BTC",
        action: "hold",
        side: "long",
        success: true,
        notional_usd: "0",
        exchange_order_id: "order-3",
        fills: [],
      },
      metadata: {},
      created_at: "2026-03-22T11:19:15.951502+00:00",
    },
    {
      asset_id: "execution-4",
      asset_type: "execution_result",
      payload: {
        coin: "SOL",
        action: "reduce",
        side: "long",
        success: true,
        notional_usd: "185.20",
        exchange_order_id: "order-4",
        fills: [
          {
            price: "162.5",
            size: "1.14",
            trade_time: "2026-03-22T11:21:15.650828Z",
          },
        ],
      },
      metadata: {},
      created_at: "2026-03-22T11:21:15.951502+00:00",
    },
  ],
};

const agentPayloads: Record<string, object> = {
  pm: {
    session: { status: "active", last_active_at: "2026-03-20T08:00:00Z" },
    latest_asset: overviewPayload.latest_strategy,
    latest_strategy: overviewPayload.latest_strategy,
    recent_assets: [overviewPayload.latest_strategy],
  },
  risk_trader: {
    session: { status: "active", last_active_at: "2026-03-20T08:20:00Z" },
    latest_asset: {
      asset_id: "batch-1",
      asset_type: "execution_batch",
      payload: {
        generated_at_utc: "2026-03-20T08:20:00Z",
        decisions: [
          {
            symbol: "BTC",
            action: "reduce",
            direction: "long",
            reason: "Momentum is cooling under headline pressure.",
          },
        ],
      },
      metadata: {},
      created_at: "2026-03-20T08:20:00Z",
    },
    latest_execution_batch: null,
    recent_assets: [],
    recent_execution_thoughts: [
      {
        generated_at_utc: "2026-03-20T08:20:00Z",
        symbol: "BTC",
        action: "reduce",
        direction: "long",
        urgency: "high",
        reason: "Momentum is cooling under headline pressure.",
        reference_take_profit_condition: "Trim into reclaim failure.",
        reference_stop_loss_condition: "If the move squeezes back through intraday highs, cut less aggressively.",
        execution_result: {
          success: true,
          notional_usd: "219.7",
        },
      },
    ],
    tactical_brief: {
      portfolio_posture: "常规推进",
      desk_focus: "本轮执行重点落在 BTC。",
      risk_bias: "风险状态正常，可按策略节奏推进",
      next_review_hint: "下一轮由 RT cadence 或风险事件唤醒。",
      trigger: {
        reason: "headline_risk",
        severity: "high",
        lock_mode: "reduce_only",
        coins: ["BTC"],
      },
      coins: [
        {
          coin: "BTC",
          working_posture: "优先减仓兑现",
          base_case: "Momentum is cooling under headline pressure.",
          preferred_add_condition: "Wait for structure to repair before adding back.",
          preferred_reduce_condition: "Trim if intraday reclaim fails.",
          reference_take_profit_condition: "Trim into reclaim failure.",
          reference_stop_loss_condition: "If intraday highs reclaim, stop reducing.",
          no_trade_zone: "Current risk lock is reduce_only.",
          force_pm_recheck_condition: "If macro risk worsens, force PM re-check.",
          next_focus: "Watch BTC response around US session.",
        },
      ],
    },
  },
  macro_event_analyst: {
    session: { status: "active", last_active_at: "2026-03-20T08:05:00Z" },
    latest_asset: newsPayload.macro_daily_memory,
    latest_macro_daily_memory: newsPayload.macro_daily_memory,
    recent_macro_events: newsPayload.macro_events,
    recent_assets: newsPayload.macro_events,
  },
  crypto_chief: {
    session: { status: "active", last_active_at: "2026-03-20T09:00:00Z" },
    latest_asset: {
      asset_id: "retro-1",
      asset_type: "chief_retro",
      payload: {
        owner_summary: "PM, RT and MEA all updated cleanly after the latest cycle.",
        round_count: 2,
        learning_completed: true,
        learning_results: [
          { agent_role: "pm", learning_summary: "PM should tighten the invalidation wording." },
        ],
      },
      metadata: {},
      created_at: "2026-03-20T09:00:00Z",
    },
    latest_chief_retro: {
      asset_id: "retro-1",
      asset_type: "chief_retro",
      payload: {
        owner_summary: "PM, RT and MEA all updated cleanly after the latest cycle.",
        round_count: 2,
        learning_completed: true,
        learning_results: [
          { agent_role: "pm", learning_summary: "PM should tighten the invalidation wording." },
        ],
      },
      metadata: {},
      created_at: "2026-03-20T09:00:00Z",
    },
    recent_assets: [],
  },
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
        if (url.includes("/api/query/agents/pm/latest")) {
          return Promise.resolve(new Response(JSON.stringify(agentPayloads.pm)));
        }
        if (url.includes("/api/query/agents/risk_trader/latest")) {
          return Promise.resolve(new Response(JSON.stringify(agentPayloads.risk_trader)));
        }
        if (url.includes("/api/query/agents/macro_event_analyst/latest")) {
          return Promise.resolve(new Response(JSON.stringify(agentPayloads.macro_event_analyst)));
        }
        if (url.includes("/api/query/agents/crypto_chief/latest")) {
          return Promise.resolve(new Response(JSON.stringify(agentPayloads.crypto_chief)));
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

  // Note: this fixture intentionally embeds a legacy 3-coin (BTC/ETH/SOL)
  // execution result to verify the UI still renders historical payloads that
  // predate the SOL retirement without crashing. Current live payloads are
  // 2-coin only.
  test("renders overview (incl. legacy SOL execution) and switches between overview plus four agent pages", async () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(screen.getByRole("heading", { name: /Openclaw Trader AI交易/ })).toBeInTheDocument());
    expect(screen.getByTestId("overview-view")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("账户余额（当前总权益）")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("5x（名义$5,012.5）")).toBeInTheDocument());
    expect(screen.queryByText("当前敞口")).not.toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText("$161.3").length).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(screen.getByText(/150\.38/)).toBeInTheDocument());
    await waitFor(() => expect(screen.getAllByText("名义占用 3.22%").length).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(screen.getByRole("button", { name: "展开更多成交回执" })).toBeInTheDocument());
    await waitFor(() => expect(screen.getByRole("button", { name: "展开更多高优先事件" })).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("卖出 BTC")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("买入 ETH")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("持有 BTC")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Fed headline turns risk sentiment colder.")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("SEC wording shifts the market toward defense.")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Exchange liquidity thins into Asia lunch.")).toBeInTheDocument());
    expect(screen.queryByText("卖出 SOL")).not.toBeInTheDocument();
    expect(screen.queryByText("Dollar bid resumes and squeezes crypto beta.")).not.toBeInTheDocument();
    expect(screen.queryByText(/order-1/i)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "展开更多成交回执" }));
    await waitFor(() => expect(screen.getByText("卖出 SOL")).toBeInTheDocument());
    await waitFor(() => expect(screen.getAllByText("已回传 1 笔成交回执。").length).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(screen.getAllByText("交易方向：卖出").length).toBeGreaterThanOrEqual(2));
    fireEvent.click(screen.getByRole("button", { name: "展开更多高优先事件" }));
    await waitFor(() => expect(screen.getByText("Dollar bid resumes and squeezes crypto beta.")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "PM" }));
    await waitFor(() => expect(screen.getByTestId("pm-view")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Portfolio Manager")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("当前正式策略")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("翻向条件")).toBeInTheDocument());
    await waitFor(() =>
      expect(
        screen.getByText("If higher-timeframe structure fails together with a macro regime turn, flip instead of only trimming."),
      ).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "RT" }));
    await waitFor(() => expect(screen.getByTestId("rt-view")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Risk Trader")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("RT 战术地图")).toBeInTheDocument());
    await waitFor(() => expect(screen.getAllByText("Momentum is cooling under headline pressure.").length).toBeGreaterThanOrEqual(1));

    fireEvent.click(screen.getByRole("button", { name: "MEA" }));
    await waitFor(() => expect(screen.getByTestId("mea-view")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("Macro & Event Analyst")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("事件墙")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Chief" }));
    await waitFor(() => expect(screen.getByTestId("chief-view")).toBeInTheDocument());
    await waitFor(() => expect(screen.getAllByText("Crypto Chief").length).toBeGreaterThanOrEqual(1));
    await waitFor(() => expect(screen.getByText("Chief 综合判断")).toBeInTheDocument());
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
    // The standalone narrative sentence was removed; verify granularity
    // still propagates by checking the scroll caption under the chart.
    await waitFor(() => expect(screen.getByTestId("balance-viewport-caption").textContent).toMatch(/15 分钟点/));

    fireEvent.click(screen.getByRole("button", { name: "日线" }));
    await waitFor(() => expect(screen.getByTestId("balance-viewport-caption").textContent).toMatch(/日线点/));
  });

  test("renders balance chart inside a horizontal scroll container", async () => {
    const client = new QueryClient();
    render(
      <QueryClientProvider client={client}>
        <App />
      </QueryClientProvider>,
    );

    const viewport = await screen.findByTestId("balance-chart-viewport");
    expect(viewport.className).toContain("overflow-x-auto");
    expect(viewport.style.touchAction).toBe("pan-x");
    await waitFor(() => expect(screen.getByTestId("balance-viewport-caption")).toHaveTextContent("只有主图与时间轴会横向滚动"));
    const fixedAxis = screen.getByTestId("balance-chart-fixed-axis");
    expect(viewport.contains(fixedAxis)).toBe(false);
    expect(screen.getByTestId("balance-chart-fixed-axis-footer")).toBeInTheDocument();
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

  test("renders Chief retro using async-brief semantics instead of old roundtable assumptions", async () => {
    const originalChiefPayload = agentPayloads.crypto_chief;
    agentPayloads.crypto_chief = {
      session: { status: "active", last_active_at: "2026-04-14T09:00:00Z" },
      latest_asset: {
        asset_id: "retro-new",
        asset_type: "chief_retro",
        payload: {
          owner_summary: "本轮复盘确认有钱留在桌上没赚到。学习指令已在文本中写明，但没有结构化提交。",
          round_count: null,
          learning_completed: false,
          learning_results: [],
          root_cause_ranking: [
            "1. PM 防守过度：方向已被市场验证正确时紧急收紧带宽 [0,15%]→[0,10%]，看对方向下错注",
            "2. RT 执行迟缓：BTC 站上 $72K 硬止损线后未立即翻仓，ETH 顺风只建 ~1%",
          ],
          role_judgements: {
            pm: "方向判断正确✓，但资本分配严重失败✗。看对不敢加是比看错更严重的问题。",
            risk_trader: "方向转换最终正确✓，但节奏太慢、仓位太小✗。",
          },
          learning_directive_ids: [],
        },
        metadata: {},
        created_at: "2026-04-14T09:00:00Z",
      },
      latest_chief_retro: {
        asset_id: "retro-new",
        asset_type: "chief_retro",
        payload: {
          owner_summary: "本轮复盘确认有钱留在桌上没赚到。学习指令已在文本中写明，但没有结构化提交。",
          round_count: null,
          learning_completed: false,
          learning_results: [],
          root_cause_ranking: [
            "1. PM 防守过度：方向已被市场验证正确时紧急收紧带宽 [0,15%]→[0,10%]，看对方向下错注",
            "2. RT 执行迟缓：BTC 站上 $72K 硬止损线后未立即翻仓，ETH 顺风只建 ~1%",
          ],
          role_judgements: {
            pm: "方向判断正确✓，但资本分配严重失败✗。看对不敢加是比看错更严重的问题。",
            risk_trader: "方向转换最终正确✓，但节奏太慢、仓位太小✗。",
          },
          learning_directive_ids: [],
        },
        metadata: {},
        created_at: "2026-04-14T09:00:00Z",
      },
      retro_chain: {
        case_id: "case-async-1",
        retro_case: {
          case_id: "case-async-1",
          case_day_utc: "2026-04-13",
          created_at_utc: "2026-04-14T08:50:00Z",
          target_return_pct: 1,
          primary_question: "为什么今天没有赚到 1%？",
          objective_summary: "把信号、执行和消息治理拆开复盘。",
          challenge_prompts: [
            "PM 是否因为防守过度、翻向条件不清、或 band 调整过频而压缩了可赚空间？",
            "RT 是否因为执行节奏、等待确认、或缺少主动翻向而错过了可抓的战术收益？",
          ],
        },
        briefs: [
          {
            brief_id: "brief-pm-1",
            agent_role: "pm",
            created_at_utc: "2026-04-14T08:51:00Z",
            root_cause: "PM 过度保守。",
            cross_role_challenge: "MEA 推送太碎。",
            self_critique: "band 收紧太早。",
            tomorrow_change: "把翻向条件写清楚。",
          },
        ],
        learning_directives: [],
      },
      recent_assets: [],
    };

    try {
      const client = new QueryClient();
      render(
        <QueryClientProvider client={client}>
          <App />
        </QueryClientProvider>,
      );

      fireEvent.click(await screen.findByRole("button", { name: "Chief" }));

      await waitFor(() => expect(screen.getByText("角色裁决")).toBeInTheDocument());
      expect(screen.queryByText("角色评分")).not.toBeInTheDocument();
      await waitFor(() =>
        expect(
          screen.getByText("PM 是否因为防守过度、翻向条件不清、或 band 调整过频而压缩了可赚空间？"),
        ).toBeInTheDocument(),
      );
      await waitFor(() =>
        expect(
          screen.getByText("PM 防守过度：方向已被市场验证正确时紧急收紧带宽 [0,15%]→[0,10%]，看对方向下错注"),
        ).toBeInTheDocument(),
      );
      await waitFor(() => expect(screen.getByText("异步 briefs")).toBeInTheDocument());
      await waitFor(() => expect(screen.getByText("仅文本提及")).toBeInTheDocument());
      await waitFor(() =>
        expect(screen.getByText("这轮只在文本里写了学习要求，没提交结构化 learning_directives。")).toBeInTheDocument(),
      );
    } finally {
      agentPayloads.crypto_chief = originalChiefPayload;
    }
  });
});
