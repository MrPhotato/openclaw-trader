export type ViewKey = "overview" | "strategy" | "news" | "agents" | "replay";

export type AssetRecord = {
  asset_id: string;
  asset_type: string;
  trace_id?: string | null;
  actor_role?: string | null;
  group_key?: string | null;
  source_ref?: string | null;
  payload: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type EventEnvelope = {
  event_id: string;
  trace_id: string;
  source_module: string;
  event_type: string;
  entity_type: string;
  entity_id?: string | null;
  occurred_at: string;
  payload: Record<string, unknown>;
};

export type OverviewData = {
  system: Record<string, unknown>;
  latest_strategy?: AssetRecord | null;
  latest_portfolio?: AssetRecord | null;
  portfolio_history: AssetRecord[];
  latest_execution_batch?: AssetRecord | null;
  recent_execution_results: AssetRecord[];
  current_macro_events: AssetRecord[];
  agent_sessions: Array<Record<string, unknown>>;
  recent_notifications: AssetRecord[];
  recent_events: EventEnvelope[];
};

export type NewsData = {
  latest_batch?: AssetRecord | null;
  macro_events: AssetRecord[];
  macro_daily_memory?: AssetRecord | null;
};

export type ExecutionsData = {
  latest_execution_batch?: AssetRecord | null;
  results: AssetRecord[];
};

export type AgentLatestData = {
  session?: Record<string, unknown> | null;
  latest_asset?: AssetRecord | null;
  recent_assets: AssetRecord[];
};

export type ReplayData = {
  trace_id?: string | null;
  events: EventEnvelope[];
  states: Array<Record<string, unknown>>;
  render_hints: Record<string, unknown>;
};

export type StreamPayload = {
  overview: OverviewData;
  events: EventEnvelope[];
};

export type MarketContextData = {
  market_context: Record<
    string,
    {
      coin?: string;
      captured_at?: string;
      shape_summary?: string;
      breakout_retest_state?: Record<string, unknown>;
      volatility_state?: Record<string, unknown>;
      compressed_price_series?: Record<
        string,
        {
          window?: string;
          change_pct?: number | null;
          points: Array<{ timestamp: number; close: string }>;
        }
      >;
    }
  >;
};
