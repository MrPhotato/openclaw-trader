export type ViewKey = "overview" | "pm" | "rt" | "mea" | "chief";

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
  risk_overlay?: {
    state?: string;
    day_peak_equity_usd?: string | number | null;
    current_equity_usd?: string | number | null;
    observe?: { drawdown_pct?: number | null; equity_usd?: string | number | null } | null;
    reduce?: { drawdown_pct?: number | null; equity_usd?: string | number | null } | null;
    exit?: { drawdown_pct?: number | null; equity_usd?: string | number | null } | null;
  } | null;
  portfolio_history: Array<{
    created_at: string;
    total_equity_usd?: string | number | null;
  }>;
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
  latest_strategy?: AssetRecord | null;
  latest_execution_batch?: AssetRecord | null;
  latest_macro_daily_memory?: AssetRecord | null;
  latest_chief_retro?: AssetRecord | null;
  retro_chain?: {
    case_id: string;
    retro_case: Record<string, unknown> | null;
    briefs: Array<Record<string, unknown>>;
    learning_directives: Array<Record<string, unknown>>;
  } | null;
  latest_rt_trigger_event?: AssetRecord | null;
  latest_risk_brake_event?: AssetRecord | null;
  latest_rt_tactical_map?: AssetRecord | null;
  recent_macro_events?: AssetRecord[];
  recent_notifications?: AssetRecord[];
  recent_execution_thoughts?: Array<Record<string, unknown>>;
  tactical_brief?: Record<string, unknown> | null;
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
