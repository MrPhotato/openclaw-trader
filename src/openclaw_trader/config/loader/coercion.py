from __future__ import annotations

import os
from pathlib import Path

from ..models import (
    AppSettings,
    BusSettings,
    ExecutionSettings,
    NewsConfig,
    NotificationSettings,
    QuantSettings,
    StorageSettings,
    SystemSettings,
    WorkflowSettings,
)
from .agents import build_agent_settings
from .factory import load_system_settings
from .paths import build_paths, runtime_root
from .secrets import safe_coinbase_credentials


def coerce_system_settings(source: object | None) -> SystemSettings:
    if source is None:
        return load_system_settings()
    if isinstance(source, SystemSettings):
        return source

    paths = build_paths(runtime_root())
    app = getattr(source, "app", None)
    model = getattr(source, "model", None)
    perps = getattr(source, "perps", None)
    workflow = getattr(source, "workflow", None)
    news = getattr(source, "news", None)
    if model is None or perps is None or workflow is None:
        raise TypeError(f"cannot coerce object of type {type(source).__name__} into SystemSettings")

    return SystemSettings(
        runtime_root=paths.runtime_root,
        app=AppSettings(
            bind_host=str(getattr(app, "bind_host", "127.0.0.1")),
            bind_port=int(getattr(app, "bind_port", 8788)),
        ),
        bus=BusSettings(),
        storage=StorageSettings(
            sqlite_path=Path(os.getenv("OPENCLAW_V2_SQLITE_PATH", str(paths.state_dir / "trader_v2.db")))
        ),
        quant=QuantSettings(
            interval=str(getattr(model, "interval", "15m")),
            history_bars=int(getattr(model, "history_bars", 1500)),
            forecast_horizons=dict(getattr(model, "forecast_horizons", {"1h": 4, "4h": 16, "12h": 48})),
            target_move_threshold_pct=float(getattr(model, "target_move_threshold_pct", 0.0025)),
            round_trip_cost_pct=float(getattr(model, "round_trip_cost_pct", 0.0012)),
            retrain_after_minutes=int(getattr(model, "retrain_after_minutes", 360)),
            min_confidence=float(getattr(model, "min_confidence", 0.43)),
            min_long_short_probability=float(getattr(model, "min_long_short_probability", 0.39)),
            meta_min_confidence=float(getattr(model, "meta_min_confidence", 0.48)),
            order_size_floor_ratio=float(getattr(model, "order_size_floor_ratio", 0.35)),
            order_size_ceiling_ratio=float(getattr(model, "order_size_ceiling_ratio", 1.0)),
            neutral_regime_size_scale=float(getattr(model, "neutral_regime_size_scale", 0.70)),
            counter_regime_size_scale=float(getattr(model, "counter_regime_size_scale", 0.60)),
            uncertainty_disagreement_caution=float(getattr(model, "uncertainty_disagreement_caution", 0.32)),
            uncertainty_disagreement_freeze=float(getattr(model, "uncertainty_disagreement_freeze", 0.45)),
            uncertainty_regime_fit_caution=float(getattr(model, "uncertainty_regime_fit_caution", 0.30)),
            uncertainty_regime_fit_freeze=float(getattr(model, "uncertainty_regime_fit_freeze", 0.24)),
            min_train_samples=int(getattr(model, "min_train_samples", 300)),
            walk_forward_splits=int(getattr(model, "walk_forward_splits", 4)),
            walk_forward_embargo_bars=int(getattr(model, "walk_forward_embargo_bars", 0)),
            high_confidence_target_coverage=float(getattr(model, "high_confidence_target_coverage", 0.30)),
            bootstrap_snapshot_exchange=getattr(model, "bootstrap_snapshot_exchange", None),
            coinalyze_api_key=getattr(model, "coinalyze_api_key", None),
            coinalyze_enabled=bool(getattr(model, "coinalyze_enabled", True)),
            coinalyze_symbols_by_coin=dict(getattr(model, "coinalyze_symbols_by_coin", {})),
            daily_macro_features_enabled=bool(getattr(model, "daily_macro_features_enabled", False)),
            min_snapshot_feature_coverage_bars=int(getattr(model, "min_snapshot_feature_coverage_bars", 48)),
            regime_states=int(getattr(model, "regime_states", 3)),
            random_seed=int(getattr(model, "random_seed", 42)),
            feature_windows=list(getattr(model, "feature_windows", [3, 6, 12, 24, 48])),
        ),
        execution=ExecutionSettings(
            exchange=str(getattr(perps, "exchange", "coinbase_intx")),
            supported_coins=[str(coin).upper() for coin in list(getattr(perps, "coins", ["BTC", "ETH"]))],
            live_enabled=bool(getattr(perps, "live_enabled", True)),
            max_leverage=float(getattr(perps, "max_leverage", 5.0)),
            max_total_exposure_pct_of_exposure_budget=float(
                getattr(
                    perps,
                    "max_total_exposure_pct_of_exposure_budget",
                    getattr(perps, "max_total_exposure_pct_of_equity", 100.0),
                )
            ),
            max_order_pct_of_exposure_budget=float(
                getattr(
                    perps,
                    "max_order_pct_of_exposure_budget",
                    getattr(perps, "max_order_share_pct_of_exposure_budget", 33.0),
                )
            ),
            max_position_pct_of_exposure_budget=float(
                getattr(
                    perps,
                    "max_position_pct_of_exposure_budget",
                    getattr(perps, "max_position_share_pct_of_exposure_budget", 66.0),
                )
            ),
            mode=str(getattr(perps, "mode", "live")),
            poll_seconds=int(getattr(perps, "poll_seconds", 60)),
            primary_coin=str(getattr(perps, "coin", "BTC")).upper(),
        ),
        workflow=WorkflowSettings(
            owner_channel=str(getattr(workflow, "owner_channel", "wecom-app")),
            owner_to=str(getattr(workflow, "owner_to", "user:owner")),
            owner_account_id=str(getattr(workflow, "owner_account_id", "default")),
            fresh_news_minutes=int(getattr(workflow, "fresh_news_minutes", 15)),
            news_keywords=[str(keyword) for keyword in list(getattr(workflow, "news_keywords", []))],
        ),
        agents=build_agent_settings(),
        notification=NotificationSettings(
            default_channel=str(getattr(workflow, "owner_channel", "wecom-app")),
            default_recipient=str(getattr(workflow, "owner_to", "user:owner")),
            chief_recipient=str(getattr(workflow, "chief_to", f"agent:{build_agent_settings().crypto_chief_agent}")),
        ),
        news=NewsConfig.model_validate(news.model_dump() if hasattr(news, "model_dump") else {}),
        coinbase=safe_coinbase_credentials(paths),
        paths=paths,
    )
