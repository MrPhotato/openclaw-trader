from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, BaseModel, Field, model_validator


class AppSettings(BaseModel):
    mode: str = "paused"
    bind_host: str = "127.0.0.1"
    bind_port: int = 8788
    primary_product: str = "BTC-USDC"
    granularity: str = "FIVE_MINUTE"
    candle_lookback: int = 48
    poll_seconds: int = 300
    allow_live_orders: bool = False
    allow_live_exits: bool = True
    initial_equity_usd: float = 207.21


class BusSettings(BaseModel):
    mode: str = "inmemory"


class RuntimePaths(BaseModel):
    runtime_root: Path
    config_dir: Path
    state_dir: Path
    data_dir: Path
    log_dir: Path
    report_dir: Path
    run_dir: Path
    model_dir: Path
    secrets_file: Path


class StorageSettings(BaseModel):
    sqlite_path: Path


class CoinbaseCredentials(BaseModel):
    api_key_id: str
    api_key_secret: str
    api_base: str = "https://api.coinbase.com"


class NewsSource(BaseModel):
    id: str
    type: str
    enabled: bool = True
    url: str
    tags: list[str] = Field(default_factory=list)
    layer: str = "news"
    max_items: int = 10


class NewsConfig(BaseModel):
    poll_seconds: int = 300
    sources: list[NewsSource] = Field(default_factory=list)


class QuantSettings(BaseModel):
    enabled: bool = True
    interval: str = "15m"
    history_bars: int = 1500
    training_history_bars_by_horizon: dict[str, int] = Field(
        default_factory=lambda: {"1h": 1500, "4h": 12000, "12h": 48000}
    )
    training_history_bars_overrides_by_coin_horizon: dict[str, int] = Field(default_factory=dict)
    forecast_horizon_bars: int = 4
    forecast_horizons: dict[str, int] = Field(default_factory=lambda: {"1h": 4, "4h": 16, "12h": 48})
    target_move_threshold_pct: float = 0.0025
    target_move_threshold_pct_overrides_by_coin_horizon: dict[str, float] = Field(
        default_factory=lambda: {"ETH:4h": 0.0025}
    )
    probability_calibration_mode_by_coin_horizon: dict[str, str] = Field(default_factory=dict)
    round_trip_cost_pct: float = 0.0012
    adaptive_labeling_enabled: bool = False
    label_volatility_window_by_horizon: dict[str, int] = Field(
        default_factory=lambda: {"1h": 12, "4h": 48, "12h": 192}
    )
    label_threshold_floor_multiplier_by_horizon: dict[str, float] = Field(
        default_factory=lambda: {"1h": 0.75, "4h": 0.60, "12h": 0.50}
    )
    label_threshold_cap_multiplier_by_horizon: dict[str, float] = Field(
        default_factory=lambda: {"1h": 2.0, "4h": 2.5, "12h": 3.0}
    )
    retrain_after_minutes: int = 360
    min_confidence: float = 0.43
    min_long_short_probability: float = 0.39
    meta_min_confidence: float = 0.48
    order_size_floor_ratio: float = 0.35
    order_size_ceiling_ratio: float = 1.0
    neutral_regime_size_scale: float = 0.70
    counter_regime_size_scale: float = 0.60
    portfolio_same_theme_caution_share: float = 0.50
    portfolio_same_theme_freeze_share: float = 0.75
    portfolio_net_directional_caution_share: float = 0.50
    portfolio_net_directional_freeze_share: float = 0.75
    portfolio_remaining_budget_caution_share: float = 0.25
    portfolio_remaining_budget_freeze_share: float = 0.10
    portfolio_extra_same_direction_penalty: float = 0.10
    uncertainty_disagreement_caution: float = 0.32
    uncertainty_disagreement_freeze: float = 0.45
    uncertainty_regime_instability_caution: float = 0.45
    uncertainty_regime_instability_freeze: float = 0.65
    uncertainty_regime_fit_caution: float = 0.30
    uncertainty_regime_fit_freeze: float = 0.24
    bootstrap_snapshot_exchange: str | None = None
    historical_open_interest_source: str = "tardis"
    tardis_api_key: str | None = None
    tardis_exchange: str = "binance-futures"
    coinalyze_api_key: str | None = None
    coinalyze_enabled: bool = True
    coinalyze_symbols_by_coin: dict[str, str] = Field(
        default_factory=lambda: {"BTC": "BTC", "ETH": "ETH"}
    )
    daily_macro_features_enabled: bool = False
    history_backfill_days: int = 540
    min_snapshot_feature_coverage_bars: int = 48
    min_train_samples: int = 300
    walk_forward_splits: int = 4
    walk_forward_embargo_bars: int = 0
    high_confidence_target_coverage: float = 0.30
    acceptance_score_components_by_horizon: dict[str, list[str]] = Field(default_factory=dict)
    acceptance_score_weights_by_coin_horizon: dict[str, dict[str, float]] = Field(default_factory=dict)
    regime_coverage_caps_by_coin_horizon: dict[str, dict[str, float]] = Field(default_factory=dict)
    specialist_horizons: list[str] = Field(default_factory=list)
    specialist_coin_horizons: list[str] = Field(default_factory=list)
    regime_states: int = 3
    random_seed: int = 42
    feature_windows: list[int] = Field(default_factory=lambda: [3, 6, 12, 24, 48])

    @model_validator(mode="after")
    def _normalize_forecast_horizons(self) -> "QuantSettings":
        defaults = {"1h": 4, "4h": 16, "12h": 48}
        raw = dict(self.forecast_horizons or {})
        merged: dict[str, int] = {}
        for label, fallback in defaults.items():
            try:
                value = int(raw.get(label, fallback))
            except Exception:
                value = fallback
            merged[label] = max(value, 1)
        self.forecast_horizons = merged
        history_defaults = {"1h": 1500, "4h": 12000, "12h": 48000}
        history_raw = dict(self.training_history_bars_by_horizon or {})
        self.training_history_bars_by_horizon = {
            label: max(int(history_raw.get(label, history_defaults[label])), self.history_bars)
            for label in defaults
        }
        self.training_history_bars_overrides_by_coin_horizon = {
            key: max(int(value), self.history_bars)
            for key, value in _normalize_coin_horizon_mapping(self.training_history_bars_overrides_by_coin_horizon).items()
        }
        self.target_move_threshold_pct_overrides_by_coin_horizon = {
            key: max(float(value), 0.0001)
            for key, value in _normalize_coin_horizon_mapping(self.target_move_threshold_pct_overrides_by_coin_horizon).items()
        }
        self.probability_calibration_mode_by_coin_horizon = {
            key: _normalize_probability_calibration_mode(value)
            for key, value in _normalize_coin_horizon_mapping(self.probability_calibration_mode_by_coin_horizon).items()
        }
        self.historical_open_interest_source = str(self.historical_open_interest_source or "tardis").strip().lower()
        if self.historical_open_interest_source not in {"tardis", "binance_rest"}:
            self.historical_open_interest_source = "tardis"
        self.tardis_api_key = str(self.tardis_api_key).strip() if self.tardis_api_key else None
        self.tardis_exchange = str(self.tardis_exchange or "binance-futures").strip() or "binance-futures"
        self.coinalyze_api_key = str(self.coinalyze_api_key).strip() if self.coinalyze_api_key else None
        self.coinalyze_symbols_by_coin = {
            str(key).strip().upper(): str(value).strip()
            for key, value in dict(self.coinalyze_symbols_by_coin or {}).items()
            if str(key).strip() and str(value).strip()
        }
        self.history_backfill_days = max(int(self.history_backfill_days or 540), 30)
        volatility_window_defaults = {"1h": 12, "4h": 48, "12h": 192}
        volatility_window_raw = dict(self.label_volatility_window_by_horizon or {})
        self.label_volatility_window_by_horizon = {
            label: max(int(volatility_window_raw.get(label, volatility_window_defaults[label])), 6)
            for label in defaults
        }
        floor_defaults = {"1h": 0.75, "4h": 0.60, "12h": 0.50}
        floor_raw = dict(self.label_threshold_floor_multiplier_by_horizon or {})
        self.label_threshold_floor_multiplier_by_horizon = {
            label: min(max(float(floor_raw.get(label, floor_defaults[label])), 0.1), 2.0)
            for label in defaults
        }
        cap_defaults = {"1h": 2.0, "4h": 2.5, "12h": 3.0}
        cap_raw = dict(self.label_threshold_cap_multiplier_by_horizon or {})
        self.label_threshold_cap_multiplier_by_horizon = {
            label: max(float(cap_raw.get(label, cap_defaults[label])), self.label_threshold_floor_multiplier_by_horizon[label])
            for label in defaults
        }
        self.forecast_horizon_bars = merged["1h"]
        self.walk_forward_embargo_bars = max(int(self.walk_forward_embargo_bars), 0)
        self.high_confidence_target_coverage = min(max(float(self.high_confidence_target_coverage), 0.05), 0.8)
        self.acceptance_score_components_by_horizon = {
            str(horizon).strip().lower(): [
                str(component).strip()
                for component in list(components or [])
                if str(component).strip()
            ]
            for horizon, components in dict(self.acceptance_score_components_by_horizon or {}).items()
            if str(horizon).strip()
        }
        normalized_weight_overrides: dict[str, dict[str, float]] = {}
        for key, payload in _normalize_coin_horizon_mapping(self.acceptance_score_weights_by_coin_horizon).items():
            normalized_weight_overrides[key] = {
                str(component).strip(): float(value)
                for component, value in dict(payload or {}).items()
                if str(component).strip()
            }
        self.acceptance_score_weights_by_coin_horizon = normalized_weight_overrides
        normalized_regime_caps: dict[str, dict[str, float]] = {}
        for key, payload in _normalize_coin_horizon_mapping(self.regime_coverage_caps_by_coin_horizon).items():
            normalized_regime_caps[key] = {
                str(regime_label): min(max(float(value), 0.0), 1.0)
                for regime_label, value in dict(payload or {}).items()
                if str(regime_label).strip()
            }
        self.regime_coverage_caps_by_coin_horizon = normalized_regime_caps
        self.specialist_horizons = sorted({str(item).strip() for item in (self.specialist_horizons or []) if str(item).strip()})
        self.specialist_coin_horizons = sorted(
            {
                normalized
                for item in (self.specialist_coin_horizons or [])
                if (normalized := _normalize_coin_horizon_key(item)) is not None
            }
        )
        return self


def _normalize_coin_horizon_key(raw: object) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if ":" not in text:
        return None
    coin, horizon = text.split(":", 1)
    coin = coin.strip().upper()
    horizon = horizon.strip().lower()
    if not coin or not horizon:
        return None
    return f"{coin}:{horizon}"


def _normalize_coin_horizon_mapping(raw_mapping: object) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, value in dict(raw_mapping or {}).items():
        normalized_key = _normalize_coin_horizon_key(key)
        if normalized_key is None:
            continue
        normalized[normalized_key] = value
    return normalized


def _normalize_probability_calibration_mode(raw: object) -> str:
    text = str(raw).strip().lower()
    if text == "flat_isotonic_rescale":
        return text
    return "dirichlet"


class RiskSettings(BaseModel):
    risk_profile: str = "normal"
    max_order_quote_usd: float | None = None
    max_position_quote_usd: float | None = None
    max_order_pct_of_exposure_budget: float = Field(
        default=33.0,
        validation_alias=AliasChoices(
            "max_order_pct_of_exposure_budget",
            "max_order_pct_of_equity",
        ),
    )
    max_position_pct_of_exposure_budget: float = Field(
        default=66.0,
        validation_alias=AliasChoices(
            "max_position_pct_of_exposure_budget",
            "max_position_pct_of_equity",
        ),
    )
    daily_loss_limit_pct_of_equity: float = 10.0
    emergency_exit_enabled: bool = True
    position_observe_drawdown_pct: float = 1.6
    position_reduce_drawdown_pct: float = 2.8
    position_exit_drawdown_pct: float = 4.0
    portfolio_peak_observe_drawdown_pct: float = 1.2
    portfolio_peak_reduce_drawdown_pct: float = 2.0
    portfolio_peak_exit_drawdown_pct: float = 3.2
    emergency_exit_on_exchange_status: bool = True
    max_live_orders_per_day: int = 5
    max_leverage: float = 5.0
    symbol_whitelist: list[str] = Field(default_factory=lambda: ["BTC-USDC"])
    require_news_confirmation: bool = False


class ExecutionSettings(BaseModel):
    enabled: bool = True
    exchange: str = "coinbase_intx"
    supported_coins: list[str] = Field(default_factory=list)
    live_enabled: bool = True
    max_leverage: float = 5.0
    max_total_exposure_pct_of_exposure_budget: float = Field(
        default=100.0,
        validation_alias=AliasChoices(
            "max_total_exposure_pct_of_exposure_budget",
            "max_total_exposure_pct_of_equity",
        ),
    )
    max_order_pct_of_exposure_budget: float = Field(
        default=33.0,
        validation_alias=AliasChoices(
            "max_order_pct_of_exposure_budget",
            "max_order_share_pct_of_exposure_budget",
        ),
    )
    max_position_pct_of_exposure_budget: float = Field(
        default=66.0,
        validation_alias=AliasChoices(
            "max_position_pct_of_exposure_budget",
            "max_position_share_pct_of_exposure_budget",
        ),
    )
    mode: str = "live"
    poll_seconds: int = 60
    primary_coin: str = "BTC"
    paper_starting_equity_usd: float = 207.21
    api_base: str = "https://api.coinbase.com"
    wallet_address: str | None = None


class OrchestratorSettings(BaseModel):
    enabled: bool = True
    market_mode: str = "perps"
    enable_observe_notifications: bool = False
    scan_interval_seconds: int = 60
    llm_fallback_minutes: int = 60
    daily_report_hour: int = 21
    daily_report_timezone: str = "Asia/Shanghai"
    reply_channel: str = "wecom-app"
    reply_to: str = "user:owner"
    reply_account_id: str = "default"
    thinking: str = "minimal"
    timeout_seconds: int = 180
    process_timeout_grace_seconds: int = 15
    runtime_bridge_enabled: bool = True
    runtime_bridge_refresh_interval_seconds: int = 10
    runtime_bridge_max_age_seconds: int = 30
    retro_prep_enabled: bool = False
    retro_prep_scan_interval_seconds: int = 60
    retro_prep_hour_utc: int = 22
    retro_prep_minute_utc: int = 40
    retro_prep_chief_job_id: str = "6b0359fe-f8e4-4f82-9671-3b9c28c49299"
    retro_prep_cron_subprocess_timeout_seconds: int = 15
    retro_prep_openclaw_bin: str = "openclaw"
    rt_event_trigger_enabled: bool = False
    rt_event_trigger_job_id: str = "ccbf7286-dba4-4d57-bebe-932340374492"
    rt_event_trigger_scan_interval_seconds: int = 30
    rt_event_trigger_global_cooldown_seconds: int = 300
    rt_event_trigger_key_cooldown_seconds: int = 900
    rt_event_trigger_max_runs_per_hour: int = 4
    rt_event_trigger_position_heartbeat_minutes: int = 60
    rt_event_trigger_flat_heartbeat_minutes: int = 120
    rt_event_trigger_exposure_drift_pct_of_exposure_budget: float = 2.0
    rt_event_trigger_execution_followup_delay_seconds: int = 180
    rt_event_trigger_cron_subprocess_timeout_seconds: int = 15
    rt_event_trigger_openclaw_bin: str = "openclaw"
    pm_scheduled_recheck_enabled: bool = False
    pm_scheduled_recheck_job_id: str = "d4153cc9-1cbf-431d-b45a-d822054672c5"
    pm_scheduled_recheck_scan_interval_seconds: int = 30
    pm_scheduled_recheck_cron_subprocess_timeout_seconds: int = 15
    pm_scheduled_recheck_openclaw_bin: str = "openclaw"
    risk_brake_enabled: bool = False
    risk_brake_scan_interval_seconds: int = 30
    risk_brake_rt_job_id: str = "ccbf7286-dba4-4d57-bebe-932340374492"
    risk_brake_pm_job_id: str = "d4153cc9-1cbf-431d-b45a-d822054672c5"
    risk_brake_cron_subprocess_timeout_seconds: int = 15
    risk_brake_openclaw_bin: str = "openclaw"
    # ------------------------------------------------------------------
    # AgentWakeMonitor: rule-driven wake dispatcher (Layer 3 of WO scheduler)
    # Fires agent turns into explicit sessions (usually `agent:<role>:main`)
    # on cron_time / max_silence_since predicates. See
    # modules/workflow_orchestrator/agent_wake.py for semantics.
    # ------------------------------------------------------------------
    agent_wake_enabled: bool = False
    agent_wake_scan_interval_seconds: int = 60
    agent_wake_openclaw_bin: str = "openclaw"
    agent_wake_subprocess_timeout_seconds: int = 15
    agent_wake_rules: list[dict[str, object]] = Field(default_factory=list)
    # ------------------------------------------------------------------
    # Agent LLM-failure → owner wecom alert (closes the gap where WO
    # blindly retries every 30min into a quota-dead agent and the owner
    # only finds out hours later). Tails gateway.err.log, recognises
    # well-known fatal patterns (ChatGPT weekly limit, bailian month
    # quota, OAuth expiry), debounces per (provider × failure_kind).
    # See modules/workflow_orchestrator/agent_failure_alert.py.
    # ------------------------------------------------------------------
    agent_failure_alert_enabled: bool = False
    agent_failure_alert_scan_interval_seconds: int = 60
    agent_failure_alert_cooldown_minutes: int = 60
    agent_failure_alert_log_path: str = "~/.openclaw/logs/gateway.err.log"
    agent_failure_alert_tail_bytes: int = 524288
    # ------------------------------------------------------------------
    # Price-conditioned PM recheck (event-driven sibling of
    # scheduled_recheck). PM authors `price_rechecks` on each strategy;
    # PriceRecheckMonitor evaluates them every ~30s against
    # runtime_bridge_state.context and dispatches PM via session_send +
    # pm_trigger_event when any subscription's condition is satisfied.
    # See modules/workflow_orchestrator/price_recheck.py.
    # ------------------------------------------------------------------
    price_recheck_enabled: bool = False
    price_recheck_scan_interval_seconds: int = 30
    price_recheck_global_cooldown_seconds: int = 60
    price_recheck_pm_session_key: str = "agent:pm:main"
    price_recheck_cron_subprocess_timeout_seconds: int = 15
    price_recheck_openclaw_bin: str = "openclaw"
    # ------------------------------------------------------------------
    # Macro data: non-crypto reference prices injected into runtime_pack
    # (Brent/WTI/DXY/10Y + BTC ETF activity + Fear & Greed). Fetched from
    # yfinance + alternative.me, cached in-process, refreshed by
    # RuntimeBridgeMonitor. See modules/trade_gateway/macro_data/.
    # ------------------------------------------------------------------
    macro_data_enabled: bool = False
    macro_data_refresh_interval_seconds: int = 900
    macro_data_http_timeout_seconds: int = 10
    macro_data_etf_tickers: list[str] = Field(default_factory=lambda: ["IBIT", "FBTC", "ARKB"])
    # ------------------------------------------------------------------
    # PM submit-gate (spec 015 FR-005). price_breach threshold in %: any
    # coin's |mark delta since previous strategy submit| ≥ this value
    # counts as an external trigger. Runtime-tunable via dispatch.yaml;
    # no restart semantics (new pulls pick up the new value on next
    # SystemSettings reload).
    # ------------------------------------------------------------------
    pm_submit_gate_price_breach_pct: float = 1.5


class StrategySettings(BaseModel):
    daily_hour: int = 21
    daily_hours: list[int] = Field(default_factory=lambda: [9, 21])
    timezone: str = "Asia/Shanghai"
    rewrite_cooldown_minutes: int = 30
    regime_shift_confirmation_minutes: int = 15
    regime_shift_confirmation_rounds: int = 3
    regime_shift_rewrite_cooldown_minutes: int = 180
    material_position_change_pct: float = 2.0
    material_order_change_pct: float = 1.0
    material_leverage_change: float = 0.25
    enable_neutral_signal_override: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "enable_neutral_signal_override",
            "允许override决策临场开仓",
        ),
    )
    neutral_position_pct_of_exposure_budget: float = Field(
        default=0.0,
        validation_alias=AliasChoices(
            "neutral_position_pct_of_exposure_budget",
            "neutral_position_share_pct",
        ),
    )
    neutral_order_pct_of_exposure_budget: float = Field(
        default=0.0,
        validation_alias=AliasChoices(
            "neutral_order_pct_of_exposure_budget",
            "neutral_order_share_pct",
        ),
    )
    weak_signal_confidence: float = 0.70
    weak_signal_min_position_pct_of_exposure_budget: float = Field(
        default=15.0,
        validation_alias=AliasChoices(
            "weak_signal_min_position_pct_of_exposure_budget",
            "weak_signal_min_position_share_pct",
        ),
    )
    weak_signal_max_position_pct_of_exposure_budget: float = Field(
        default=25.0,
        validation_alias=AliasChoices(
            "weak_signal_max_position_pct_of_exposure_budget",
            "weak_signal_max_position_share_pct",
        ),
    )
    weak_signal_position_pct_of_exposure_budget: float = Field(
        default=20.0,
        validation_alias=AliasChoices(
            "weak_signal_position_pct_of_exposure_budget",
            "weak_signal_position_share_pct",
        ),
    )
    weak_signal_order_pct_of_exposure_budget: float = Field(
        default=15.0,
        validation_alias=AliasChoices(
            "weak_signal_order_pct_of_exposure_budget",
            "weak_signal_order_share_pct",
        ),
    )
    medium_signal_min_position_pct_of_exposure_budget: float = Field(
        default=30.0,
        validation_alias=AliasChoices(
            "medium_signal_min_position_pct_of_exposure_budget",
            "medium_signal_min_position_share_pct",
        ),
    )
    medium_signal_max_position_pct_of_exposure_budget: float = Field(
        default=50.0,
        validation_alias=AliasChoices(
            "medium_signal_max_position_pct_of_exposure_budget",
            "medium_signal_max_position_share_pct",
        ),
    )
    medium_signal_position_pct_of_exposure_budget: float = Field(
        default=40.0,
        validation_alias=AliasChoices(
            "medium_signal_position_pct_of_exposure_budget",
            "medium_signal_position_share_pct",
        ),
    )
    medium_signal_order_pct_of_exposure_budget: float = Field(
        default=25.0,
        validation_alias=AliasChoices(
            "medium_signal_order_pct_of_exposure_budget",
            "medium_signal_order_share_pct",
        ),
    )
    strong_signal_confidence: float = 0.82
    strong_signal_min_position_pct_of_exposure_budget: float = Field(
        default=50.0,
        validation_alias=AliasChoices(
            "strong_signal_min_position_pct_of_exposure_budget",
            "strong_signal_min_position_share_pct",
        ),
    )
    strong_signal_max_position_pct_of_exposure_budget: float = Field(
        default=70.0,
        validation_alias=AliasChoices(
            "strong_signal_max_position_pct_of_exposure_budget",
            "strong_signal_max_position_share_pct",
        ),
    )
    strong_signal_position_pct_of_exposure_budget: float = Field(
        default=60.0,
        validation_alias=AliasChoices(
            "strong_signal_position_pct_of_exposure_budget",
            "strong_signal_position_share_pct",
        ),
    )
    strong_signal_order_pct_of_exposure_budget: float = Field(
        default=35.0,
        validation_alias=AliasChoices(
            "strong_signal_order_pct_of_exposure_budget",
            "strong_signal_order_share_pct",
        ),
    )
    probe_min_position_pct_of_exposure_budget: float = Field(
        default=15.0,
        validation_alias=AliasChoices(
            "probe_min_position_pct_of_exposure_budget",
            "probe_min_position_share_pct",
        ),
    )
    probe_order_pct_of_exposure_budget: float = Field(
        default=15.0,
        validation_alias=AliasChoices(
            "probe_order_pct_of_exposure_budget",
            "probe_order_share_pct",
        ),
    )
    probe_aligned_scale: float = 0.75
    probe_aligned_cap_position_pct_of_exposure_budget: float = Field(
        default=25.0,
        validation_alias=AliasChoices(
            "probe_aligned_cap_position_pct_of_exposure_budget",
            "probe_aligned_cap_position_share_pct",
        ),
    )
    probe_partial_scale: float = 0.50
    probe_partial_cap_position_pct_of_exposure_budget: float = Field(
        default=20.0,
        validation_alias=AliasChoices(
            "probe_partial_cap_position_pct_of_exposure_budget",
            "probe_partial_cap_position_share_pct",
        ),
    )
    observe_cap_position_pct_of_exposure_budget: float = Field(
        default=15.0,
        validation_alias=AliasChoices(
            "observe_cap_position_pct_of_exposure_budget",
            "observe_cap_position_share_pct",
        ),
    )
    observe_cap_order_pct_of_exposure_budget: float = Field(
        default=15.0,
        validation_alias=AliasChoices(
            "observe_cap_order_pct_of_exposure_budget",
            "observe_cap_order_share_pct",
        ),
    )
    reduce_cap_position_pct_of_exposure_budget: float = Field(
        default=4.0,
        validation_alias=AliasChoices(
            "reduce_cap_position_pct_of_exposure_budget",
            "reduce_cap_position_share_pct",
        ),
    )
    reduce_cap_order_pct_of_exposure_budget: float = Field(
        default=4.0,
        validation_alias=AliasChoices(
            "reduce_cap_order_pct_of_exposure_budget",
            "reduce_cap_order_share_pct",
        ),
    )
    exit_cap_position_pct_of_exposure_budget: float = Field(
        default=0.0,
        validation_alias=AliasChoices(
            "exit_cap_position_pct_of_exposure_budget",
            "exit_cap_position_share_pct",
        ),
    )
    exit_cap_order_pct_of_exposure_budget: float = Field(
        default=0.0,
        validation_alias=AliasChoices(
            "exit_cap_order_pct_of_exposure_budget",
            "exit_cap_order_share_pct",
        ),
    )
    funding_hot_threshold: float = 0.0005
    funding_hot_scale: float = 0.75
    rewrite_layers: list[str] = Field(
        default_factory=lambda: [
            "macro",
            "regulation",
            "exchange-status",
            "exchange-announcement",
            "official-x",
            "event-calendar",
        ]
    )
    rewrite_severities: list[str] = Field(default_factory=lambda: ["high"])
    track_products: list[str] = Field(default_factory=lambda: ["BTC", "ETH"])

    @model_validator(mode="before")
    @classmethod
    def _normalize_daily_hours(cls, raw: object) -> object:
        if not isinstance(raw, dict):
            return raw
        payload = dict(raw)
        if "daily_hours" not in payload:
            daily_hour = payload.get("daily_hour")
            if daily_hour is not None:
                payload["daily_hours"] = [daily_hour]
        elif isinstance(payload.get("daily_hours"), int):
            payload["daily_hours"] = [payload["daily_hours"]]
        return payload


class WorkflowSettings(BaseModel):
    entry_mode: str = "confirm"
    auto_preview_on_signal: bool = True
    preview_min_confidence: float = 0.60
    signal_notify_cooldown_minutes: int = 60
    news_notify_cooldown_minutes: int = 60
    panic_notify_cooldown_minutes: int = 10
    fresh_news_minutes: int = 15
    news_keywords: list[str] = Field(default_factory=list)
    owner_channel: str = "wecom-app"
    owner_to: str = "user:owner"
    owner_account_id: str = "default"


class AgentSettings(BaseModel):
    pm_agent: str = "pm"
    risk_trader_agent: str = "risk-trader"
    macro_event_analyst_agent: str = "macro-event-analyst"
    crypto_chief_agent: str = "crypto-chief"
    openclaw_enabled: bool = False
    openclaw_timeout_seconds: int = 60


class NotificationSettings(BaseModel):
    default_channel: str
    default_recipient: str
    chief_recipient: str | None = None


class SystemSettings(BaseModel):
    runtime_root: Path
    app: AppSettings = Field(default_factory=AppSettings)
    bus: BusSettings
    storage: StorageSettings
    quant: QuantSettings
    risk: RiskSettings = Field(default_factory=RiskSettings)
    execution: ExecutionSettings
    orchestrator: OrchestratorSettings = Field(default_factory=OrchestratorSettings)
    strategy: StrategySettings = Field(default_factory=StrategySettings)
    workflow: WorkflowSettings
    agents: AgentSettings
    notification: NotificationSettings
    news: NewsConfig = Field(default_factory=NewsConfig)
    coinbase: CoinbaseCredentials | None = None
    paths: RuntimePaths | None = None

    def model_post_init(self, __context) -> None:
        if self.paths is None:
            root = self.runtime_root
            self.paths = RuntimePaths(
                runtime_root=root,
                config_dir=root / "config",
                state_dir=root / "state",
                data_dir=root / "data",
                log_dir=root / "logs",
                report_dir=root / "reports",
                run_dir=root / "run",
                model_dir=root / "models",
                secrets_file=root / "secrets" / "coinbase.env",
            )
