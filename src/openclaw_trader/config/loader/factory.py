from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from ..models import (
    AppSettings,
    BusSettings,
    ExecutionSettings,
    NewsConfig,
    NotificationSettings,
    OrchestratorSettings,
    QuantSettings,
    RiskSettings,
    StorageSettings,
    StrategySettings,
    SystemSettings,
    WorkflowSettings,
)
from .agents import build_agent_settings
from .paths import build_paths, runtime_root
from .secrets import safe_coinbase_credentials
from .yaml_loader import load_yaml, normalized_forecast_horizons


def build_system_settings_from_paths(paths) -> SystemSettings:
    app_payload = load_yaml(paths.config_dir / "app.yaml")
    risk_payload = load_yaml(paths.config_dir / "risk.yaml")
    dispatch_payload = load_yaml(paths.config_dir / "dispatch.yaml")
    strategy_payload = load_yaml(paths.config_dir / "strategy.yaml")
    model_payload = load_yaml(paths.config_dir / "model.yaml")
    perps_payload = load_yaml(paths.config_dir / "perps.yaml")
    workflow_payload = load_yaml(paths.config_dir / "workflow.yaml")
    agent_payload = load_yaml(paths.config_dir / "agents.yaml")
    news_payload = load_yaml(paths.config_dir / "news.yaml")
    rabbitmq_url = os.getenv("OPENCLAW_V2_RABBITMQ_URL", "amqp://guest:guest@127.0.0.1:5672/%2F")
    exchange_name = os.getenv("OPENCLAW_V2_EXCHANGE", "openclaw.topic")
    sqlite_path = Path(os.getenv("OPENCLAW_V2_SQLITE_PATH", str(paths.state_dir / "trader_v2.db")))

    quant_payload = dict(model_payload)
    quant_payload["forecast_horizons"] = normalized_forecast_horizons(model_payload)

    return SystemSettings(
        runtime_root=paths.runtime_root,
        app=AppSettings(
            mode=str(app_payload.get("mode", "paused")),
            bind_host=str(app_payload.get("bind_host", "127.0.0.1")),
            bind_port=int(app_payload.get("bind_port", 8788)),
            primary_product=str(app_payload.get("primary_product", "BTC-USDC")),
            granularity=str(app_payload.get("granularity", "FIVE_MINUTE")),
            candle_lookback=int(app_payload.get("candle_lookback", 48)),
            poll_seconds=int(app_payload.get("poll_seconds", 300)),
            allow_live_orders=bool(app_payload.get("allow_live_orders", False)),
            allow_live_exits=bool(app_payload.get("allow_live_exits", True)),
            initial_equity_usd=float(app_payload.get("initial_equity_usd", 207.21)),
        ),
        bus=BusSettings(
            rabbitmq_url=rabbitmq_url,
            exchange_name=exchange_name,
        ),
        storage=StorageSettings(sqlite_path=sqlite_path),
        quant=QuantSettings.model_validate(quant_payload),
        risk=RiskSettings.model_validate(risk_payload),
        execution=ExecutionSettings(
            enabled=bool(perps_payload.get("enabled", True)),
            exchange=str(perps_payload.get("exchange", "coinbase_intx")),
            supported_coins=[str(coin).upper() for coin in list(perps_payload.get("coins") or ["BTC", "ETH", "SOL"])],
            live_enabled=bool(perps_payload.get("live_enabled", True)),
            max_leverage=float(perps_payload.get("max_leverage", 5.0)),
            max_total_exposure_pct_of_equity=float(perps_payload.get("max_total_exposure_pct_of_equity", 100.0)),
            max_order_share_pct_of_exposure_budget=float(perps_payload.get("max_order_share_pct_of_exposure_budget", 33.0)),
            max_position_share_pct_of_exposure_budget=float(perps_payload.get("max_position_share_pct_of_exposure_budget", 66.0)),
            mode=str(perps_payload.get("mode", "live")),
            poll_seconds=int(perps_payload.get("poll_seconds", 60)),
            primary_coin=str(perps_payload.get("coin", "BTC")).upper(),
            paper_starting_equity_usd=float(perps_payload.get("paper_starting_equity_usd", 207.21)),
            api_base=str(perps_payload.get("api_base", "https://api.coinbase.com")),
            wallet_address=perps_payload.get("wallet_address"),
        ),
        orchestrator=OrchestratorSettings(
            enabled=bool(dispatch_payload.get("enabled", True)),
            market_mode=str(dispatch_payload.get("market_mode", "perps")),
            enable_observe_notifications=bool(dispatch_payload.get("enable_observe_notifications", False)),
            scan_interval_seconds=int(dispatch_payload.get("scan_interval_seconds", 60)),
            llm_fallback_minutes=int(dispatch_payload.get("llm_fallback_minutes", 60)),
            daily_report_hour=int(dispatch_payload.get("daily_report_hour", 21)),
            daily_report_timezone=str(dispatch_payload.get("daily_report_timezone", "Asia/Shanghai")),
            reply_channel=str(dispatch_payload.get("reply_channel", "wecom-app")),
            reply_to=str(dispatch_payload.get("reply_to", "user:owner")),
            reply_account_id=str(dispatch_payload.get("reply_account_id", "default")),
            thinking=str(dispatch_payload.get("thinking", "minimal")),
            timeout_seconds=int(dispatch_payload.get("timeout_seconds", 180)),
            process_timeout_grace_seconds=int(dispatch_payload.get("process_timeout_grace_seconds", 15)),
        ),
        strategy=StrategySettings.model_validate(strategy_payload),
        workflow=WorkflowSettings(
            entry_mode=str(workflow_payload.get("entry_mode", "confirm")),
            auto_preview_on_signal=bool(workflow_payload.get("auto_preview_on_signal", True)),
            preview_min_confidence=float(workflow_payload.get("preview_min_confidence", 0.60)),
            signal_notify_cooldown_minutes=int(workflow_payload.get("signal_notify_cooldown_minutes", 60)),
            news_notify_cooldown_minutes=int(workflow_payload.get("news_notify_cooldown_minutes", 60)),
            panic_notify_cooldown_minutes=int(workflow_payload.get("panic_notify_cooldown_minutes", 10)),
            fresh_news_minutes=int(workflow_payload.get("fresh_news_minutes", 15)),
            news_keywords=[str(keyword) for keyword in list(workflow_payload.get("news_keywords") or [])],
            owner_channel=str(workflow_payload.get("owner_channel", "wecom-app")),
            owner_to=str(workflow_payload.get("owner_to", "user:owner")),
            owner_account_id=str(workflow_payload.get("owner_account_id", "default")),
        ),
        agents=build_agent_settings(agent_payload),
        notification=NotificationSettings(
            default_channel=str(workflow_payload.get("owner_channel", "wecom-app")),
            default_recipient=str(workflow_payload.get("owner_to", "user:owner")),
            chief_recipient=str(workflow_payload.get("chief_to", f"agent:{build_agent_settings(agent_payload).crypto_chief_agent}")),
        ),
        news=NewsConfig.model_validate(news_payload),
        coinbase=safe_coinbase_credentials(paths),
        paths=paths,
    )


@lru_cache(maxsize=1)
def load_system_settings() -> SystemSettings:
    return build_system_settings_from_paths(build_paths(runtime_root()))
