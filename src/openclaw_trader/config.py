from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import dotenv_values
from pydantic import AliasChoices, BaseModel, Field, model_validator

from .models import EntryWorkflowMode, RiskProfile, TraderMode


RUNTIME_ROOT = Path.home() / ".openclaw-trader"
SECRETS_FILE = RUNTIME_ROOT / "secrets" / "coinbase.env"
CONFIG_DIR = RUNTIME_ROOT / "config"
STATE_DIR = RUNTIME_ROOT / "state"
DATA_DIR = RUNTIME_ROOT / "data"
LOG_DIR = RUNTIME_ROOT / "logs"
REPORT_DIR = RUNTIME_ROOT / "reports"
RUN_DIR = RUNTIME_ROOT / "run"
MODEL_DIR = RUNTIME_ROOT / "models"
DB_PATH = STATE_DIR / "trader.db"


class AppConfig(BaseModel):
    mode: TraderMode = TraderMode.paused
    bind_host: str = "127.0.0.1"
    bind_port: int = 8788
    primary_product: str = "BTC-USDC"
    granularity: str = "FIVE_MINUTE"
    candle_lookback: int = 48
    poll_seconds: int = 300
    allow_live_orders: bool = False
    allow_live_exits: bool = True
    initial_equity_usd: float = 207.21


class RiskConfig(BaseModel):
    risk_profile: RiskProfile = RiskProfile.normal
    max_order_quote_usd: float | None = None
    max_position_quote_usd: float | None = None
    max_order_pct_of_equity: float = 15.0
    max_position_pct_of_equity: float = 35.0
    daily_loss_limit_pct_of_equity: float = 6.0
    emergency_exit_enabled: bool = True
    position_observe_drawdown_pct: float = 4.0
    position_reduce_drawdown_pct: float = 7.0
    position_exit_drawdown_pct: float = 10.0
    emergency_exit_on_exchange_status: bool = True
    max_live_orders_per_day: int = 5
    max_leverage: float = 1.0
    symbol_whitelist: list[str] = Field(default_factory=lambda: ["BTC-USDC"])
    require_news_confirmation: bool = False


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


class PerpConfig(BaseModel):
    enabled: bool = True
    exchange: str = "coinbase_intx"
    mode: TraderMode = TraderMode.live
    coin: str = "BTC"
    coins: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL"])
    poll_seconds: int = 60
    paper_starting_equity_usd: float = 207.21
    max_order_share_pct_of_exposure_budget: float = Field(
        default=66.0,
        validation_alias=AliasChoices(
            "max_order_share_pct_of_exposure_budget",
            "max_order_pct_of_equity",
        ),
    )
    max_position_share_pct_of_exposure_budget: float = Field(
        default=100.0,
        validation_alias=AliasChoices(
            "max_position_share_pct_of_exposure_budget",
            "max_position_pct_of_equity",
        ),
    )
    max_total_exposure_pct_of_equity: float = 100.0
    max_leverage: float = 5.0
    live_enabled: bool = True
    api_base: str = "https://api.coinbase.com"
    wallet_address: str | None = None


class DispatchConfig(BaseModel):
    enabled: bool = True
    market_mode: str = "perps"
    enable_observe_notifications: bool = False
    scan_interval_seconds: int = 300
    llm_fallback_minutes: int = 60
    daily_report_hour: int = 21
    daily_report_timezone: str = "Asia/Shanghai"
    reply_channel: str = "owner-channel"
    reply_to: str = "user:owner"
    reply_account_id: str = "default"
    thinking: str = "minimal"
    timeout_seconds: int = 180
    process_timeout_grace_seconds: int = 15


class StrategyConfig(BaseModel):
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
    neutral_position_share_pct: float = Field(
        default=0.0,
        validation_alias=AliasChoices("neutral_position_share_pct", "neutral_position_pct"),
    )
    neutral_order_share_pct: float = Field(
        default=0.0,
        validation_alias=AliasChoices("neutral_order_share_pct", "neutral_order_pct"),
    )
    weak_signal_confidence: float = 0.70
    weak_signal_min_position_share_pct: float = Field(
        default=10.0,
        validation_alias=AliasChoices("weak_signal_min_position_share_pct"),
    )
    weak_signal_max_position_share_pct: float = Field(
        default=20.0,
        validation_alias=AliasChoices("weak_signal_max_position_share_pct"),
    )
    weak_signal_position_share_pct: float = Field(
        default=8.0,
        validation_alias=AliasChoices("weak_signal_position_share_pct", "weak_signal_position_pct"),
    )
    weak_signal_order_share_pct: float = Field(
        default=4.0,
        validation_alias=AliasChoices("weak_signal_order_share_pct", "weak_signal_order_pct"),
    )
    strong_signal_confidence: float = 0.82
    strong_signal_min_position_share_pct: float = Field(
        default=40.0,
        validation_alias=AliasChoices("strong_signal_min_position_share_pct"),
    )
    strong_signal_max_position_share_pct: float = Field(
        default=60.0,
        validation_alias=AliasChoices("strong_signal_max_position_share_pct"),
    )
    strong_signal_position_share_pct: float = Field(
        default=20.0,
        validation_alias=AliasChoices("strong_signal_position_share_pct", "strong_signal_position_pct"),
    )
    strong_signal_order_share_pct: float = Field(
        default=8.0,
        validation_alias=AliasChoices("strong_signal_order_share_pct", "strong_signal_order_pct"),
    )
    medium_signal_min_position_share_pct: float = Field(
        default=20.0,
        validation_alias=AliasChoices("medium_signal_min_position_share_pct"),
    )
    medium_signal_max_position_share_pct: float = Field(
        default=40.0,
        validation_alias=AliasChoices("medium_signal_max_position_share_pct"),
    )
    medium_signal_position_share_pct: float = Field(
        default=14.0,
        validation_alias=AliasChoices("medium_signal_position_share_pct", "medium_signal_position_pct"),
    )
    medium_signal_order_share_pct: float = Field(
        default=6.0,
        validation_alias=AliasChoices("medium_signal_order_share_pct", "medium_signal_order_pct"),
    )
    observe_cap_position_share_pct: float = Field(
        default=6.0,
        validation_alias=AliasChoices("observe_cap_position_share_pct", "observe_cap_position_pct"),
    )
    observe_cap_order_share_pct: float = Field(
        default=3.0,
        validation_alias=AliasChoices("observe_cap_order_share_pct", "observe_cap_order_pct"),
    )
    reduce_cap_position_share_pct: float = Field(
        default=3.0,
        validation_alias=AliasChoices("reduce_cap_position_share_pct", "reduce_cap_position_pct"),
    )
    reduce_cap_order_share_pct: float = Field(
        default=1.5,
        validation_alias=AliasChoices("reduce_cap_order_share_pct", "reduce_cap_order_pct"),
    )
    exit_cap_position_share_pct: float = Field(
        default=0.0,
        validation_alias=AliasChoices("exit_cap_position_share_pct", "exit_cap_position_pct"),
    )
    exit_cap_order_share_pct: float = Field(
        default=0.0,
        validation_alias=AliasChoices("exit_cap_order_share_pct", "exit_cap_order_pct"),
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
    track_products: list[str] = Field(default_factory=lambda: ["BTC", "ETH", "SOL"])

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


class ModelConfig(BaseModel):
    enabled: bool = True
    interval: str = "15m"
    history_bars: int = 1500
    forecast_horizon_bars: int = 4
    target_move_threshold_pct: float = 0.0025
    min_train_samples: int = 300
    retrain_after_minutes: int = 360
    regime_states: int = 3
    random_seed: int = 42
    min_confidence: float = 0.46
    min_long_short_probability: float = 0.42
    order_size_floor_ratio: float = 0.35
    order_size_ceiling_ratio: float = 1.0
    neutral_regime_size_scale: float = 0.70
    counter_regime_size_scale: float = 0.60
    feature_windows: list[int] = Field(default_factory=lambda: [3, 6, 12, 24, 48])


class WorkflowConfig(BaseModel):
    entry_mode: EntryWorkflowMode = EntryWorkflowMode.confirm
    auto_preview_on_signal: bool = True
    preview_min_confidence: float = 0.60
    signal_notify_cooldown_minutes: int = 60
    news_notify_cooldown_minutes: int = 60
    panic_notify_cooldown_minutes: int = 10
    fresh_news_minutes: int = 30
    news_keywords: list[str] = Field(
        default_factory=lambda: [
            "bitcoin",
            "btc",
            "etf",
            "fed",
            "fomc",
            "cpi",
            "inflation",
            "sec",
            "digital asset",
            "stablecoin",
            "rate",
            "rates",
            "powell",
            "monetary policy",
            "ethereum",
            "eth",
            "sol",
            "solana",
            "coinbase",
            "intx",
            "funding",
            "open interest",
            "liquidation",
            "listing",
            "maintenance",
            "perpetual",
            "futures",
        ]
    )
    owner_channel: str = "owner-channel"
    owner_to: str = "user:owner"
    owner_account_id: str = "default"


@dataclass
class CoinbaseCredentials:
    api_key_id: str
    api_key_secret: str
    api_base: str = "https://api.coinbase.com"


class RuntimeConfig(BaseModel):
    app: AppConfig
    risk: RiskConfig
    news: NewsConfig
    perps: PerpConfig
    dispatch: DispatchConfig
    strategy: StrategyConfig
    model: ModelConfig = Field(default_factory=ModelConfig)
    workflow: WorkflowConfig


def _load_yaml(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    data = yaml.safe_load(path.read_text())
    return data or default


def load_coinbase_credentials() -> CoinbaseCredentials:
    values = dotenv_values(SECRETS_FILE)
    api_key_id = values.get("COINBASE_API_KEY_ID", "")
    api_key_secret = values.get("COINBASE_API_KEY_SECRET", "")
    api_base = values.get("COINBASE_API_BASE", "https://api.coinbase.com")
    if not api_key_id or not api_key_secret:
        raise ValueError(f"Coinbase credentials missing in {SECRETS_FILE}")
    return CoinbaseCredentials(
        api_key_id=api_key_id,
        api_key_secret=api_key_secret,
        api_base=api_base,
    )


def load_runtime_config() -> RuntimeConfig:
    app = AppConfig.model_validate(_load_yaml(CONFIG_DIR / "app.yaml", {}))
    risk = RiskConfig.model_validate(_load_yaml(CONFIG_DIR / "risk.yaml", {}))
    news = NewsConfig.model_validate(_load_yaml(CONFIG_DIR / "news.yaml", {}))
    perps = PerpConfig.model_validate(_load_yaml(CONFIG_DIR / "perps.yaml", {}))
    dispatch = DispatchConfig.model_validate(_load_yaml(CONFIG_DIR / "dispatch.yaml", {}))
    strategy = StrategyConfig.model_validate(_load_yaml(CONFIG_DIR / "strategy.yaml", {}))
    model = ModelConfig.model_validate(_load_yaml(CONFIG_DIR / "model.yaml", {}))
    workflow = WorkflowConfig.model_validate(_load_yaml(CONFIG_DIR / "workflow.yaml", {}))
    return RuntimeConfig(app=app, risk=risk, news=news, perps=perps, dispatch=dispatch, strategy=strategy, model=model, workflow=workflow)


def save_app_config(app: AppConfig) -> None:
    (CONFIG_DIR / "app.yaml").write_text(
        yaml.safe_dump(app.model_dump(mode="json"), sort_keys=False)
    )


def save_workflow_config(workflow: WorkflowConfig) -> None:
    (CONFIG_DIR / "workflow.yaml").write_text(
        yaml.safe_dump(workflow.model_dump(mode="json"), sort_keys=False)
    )
