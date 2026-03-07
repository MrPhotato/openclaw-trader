from __future__ import annotations

from pathlib import Path

import yaml

from .config import CONFIG_DIR, DATA_DIR, LOG_DIR, MODEL_DIR, REPORT_DIR, RUN_DIR, RUNTIME_ROOT, STATE_DIR


DEFAULT_APP = {
    "mode": "paused",
    "bind_host": "127.0.0.1",
    "bind_port": 8788,
    "primary_product": "BTC-USDC",
    "granularity": "FIVE_MINUTE",
    "candle_lookback": 48,
    "poll_seconds": 300,
    "allow_live_orders": False,
    "allow_live_exits": True,
    "initial_equity_usd": 207.21,
}

DEFAULT_RISK = {
    "risk_profile": "normal",
    "max_order_quote_usd": None,
    "max_position_quote_usd": None,
    "max_order_pct_of_equity": 15.0,
    "max_position_pct_of_equity": 35.0,
    "daily_loss_limit_pct_of_equity": 6.0,
    "emergency_exit_enabled": True,
    "position_observe_drawdown_pct": 4.0,
    "position_reduce_drawdown_pct": 7.0,
    "position_exit_drawdown_pct": 10.0,
    "emergency_exit_on_exchange_status": True,
    "max_live_orders_per_day": 5,
    "max_leverage": 1.0,
    "symbol_whitelist": ["BTC-USDC"],
    "require_news_confirmation": False,
}

DEFAULT_NEWS = {
    "poll_seconds": 300,
    "sources": [
        {
            "id": "coindesk-rss",
            "type": "rss",
            "enabled": True,
            "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
            "tags": ["market-news", "btc"],
            "layer": "structured-news",
            "max_items": 8,
        },
        {
            "id": "coinbase-status",
            "type": "atom",
            "enabled": True,
            "url": "https://status.coinbase.com/history.atom",
            "tags": ["exchange-status", "perps"],
            "layer": "exchange-status",
            "max_items": 8,
        },
        {
            "id": "sec-press-releases",
            "type": "rss",
            "enabled": True,
            "url": "https://www.sec.gov/news/pressreleases.rss",
            "tags": ["regulation", "btc"],
            "layer": "regulation",
            "max_items": 8,
        },
        {
            "id": "fed-press-monetary",
            "type": "rss",
            "enabled": True,
            "url": "https://www.federalreserve.gov/feeds/press_monetary.xml",
            "tags": ["macro", "rates"],
            "layer": "macro",
            "max_items": 8,
        },
        {
            "id": "fed-speeches-testimony",
            "type": "rss",
            "enabled": True,
            "url": "https://www.federalreserve.gov/feeds/speeches_and_testimony.xml",
            "tags": ["macro", "policy"],
            "layer": "macro",
            "max_items": 8,
        },
        {
            "id": "fed-fomc-calendar",
            "type": "html-fed-fomc-calendar",
            "enabled": True,
            "url": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            "tags": ["event-calendar", "macro", "rates"],
            "layer": "event-calendar",
            "max_items": 8,
        },
    ],
}

DEFAULT_PERPS = {
    "enabled": True,
    "exchange": "coinbase_intx",
    "mode": "live",
    "coin": "BTC",
    "coins": ["BTC", "ETH", "SOL"],
    "poll_seconds": 60,
    "paper_starting_equity_usd": 207.21,
    "max_order_share_pct_of_exposure_budget": 66.0,
    "max_position_share_pct_of_exposure_budget": 100.0,
    "max_total_exposure_pct_of_equity": 100.0,
    "max_leverage": 5.0,
    "live_enabled": True,
    "api_base": "https://api.coinbase.com",
    "wallet_address": None,
}

DEFAULT_DISPATCH = {
    "enabled": True,
    "market_mode": "perps",
    "scan_interval_seconds": 60,
    "llm_fallback_minutes": 60,
    "daily_report_hour": 21,
    "daily_report_timezone": "Asia/Shanghai",
    "reply_channel": "owner-channel",
    "reply_to": "user:owner",
    "reply_account_id": "default",
    "thinking": "minimal",
    "timeout_seconds": 180,
}

DEFAULT_STRATEGY = {
    "daily_hour": 21,
    "daily_hours": [9, 21],
    "timezone": "Asia/Shanghai",
    "rewrite_cooldown_minutes": 30,
    "regime_shift_confirmation_minutes": 15,
    "regime_shift_confirmation_rounds": 3,
    "regime_shift_rewrite_cooldown_minutes": 180,
    "material_position_change_pct": 2.0,
    "material_order_change_pct": 1.0,
    "material_leverage_change": 0.25,
    "允许override决策临场开仓": False,
    "neutral_position_share_pct": 0.0,
    "neutral_order_share_pct": 0.0,
    "weak_signal_confidence": 0.70,
    "weak_signal_min_position_share_pct": 10.0,
    "weak_signal_max_position_share_pct": 20.0,
    "weak_signal_position_share_pct": 8.0,
    "weak_signal_order_share_pct": 4.0,
    "strong_signal_confidence": 0.82,
    "strong_signal_min_position_share_pct": 40.0,
    "strong_signal_max_position_share_pct": 60.0,
    "strong_signal_position_share_pct": 20.0,
    "strong_signal_order_share_pct": 8.0,
    "medium_signal_min_position_share_pct": 20.0,
    "medium_signal_max_position_share_pct": 40.0,
    "medium_signal_position_share_pct": 14.0,
    "medium_signal_order_share_pct": 6.0,
    "observe_cap_position_share_pct": 6.0,
    "observe_cap_order_share_pct": 3.0,
    "reduce_cap_position_share_pct": 3.0,
    "reduce_cap_order_share_pct": 1.5,
    "exit_cap_position_share_pct": 0.0,
    "exit_cap_order_share_pct": 0.0,
    "funding_hot_threshold": 0.0005,
    "funding_hot_scale": 0.75,
    "rewrite_layers": [
        "macro",
        "regulation",
        "exchange-status",
        "exchange-announcement",
        "official-x",
        "event-calendar",
    ],
    "rewrite_severities": ["high"],
    "track_products": ["BTC", "ETH", "SOL"],
}

DEFAULT_MODEL = {
    "enabled": True,
    "interval": "15m",
    "history_bars": 1500,
    "forecast_horizon_bars": 4,
    "target_move_threshold_pct": 0.0025,
    "min_train_samples": 300,
    "retrain_after_minutes": 360,
    "regime_states": 3,
    "random_seed": 42,
    "min_confidence": 0.46,
    "min_long_short_probability": 0.42,
    "order_size_floor_ratio": 0.35,
    "order_size_ceiling_ratio": 1.0,
    "neutral_regime_size_scale": 0.70,
    "counter_regime_size_scale": 0.60,
    "feature_windows": [3, 6, 12, 24, 48],
}

DEFAULT_WORKFLOW = {
    "entry_mode": "confirm",
    "auto_preview_on_signal": True,
    "preview_min_confidence": 0.60,
    "signal_notify_cooldown_minutes": 60,
    "news_notify_cooldown_minutes": 60,
    "panic_notify_cooldown_minutes": 10,
    "fresh_news_minutes": 30,
    "news_keywords": [
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
        "coinbase",
        "intx",
        "funding",
        "open interest",
        "liquidation",
        "listing",
        "maintenance",
        "perpetual",
        "futures",
    ],
    "owner_channel": "owner-channel",
    "owner_to": "user:owner",
    "owner_account_id": "default",
}


def ensure_runtime_layout() -> None:
    for path in [RUNTIME_ROOT, CONFIG_DIR, DATA_DIR, LOG_DIR, MODEL_DIR, REPORT_DIR, RUN_DIR, STATE_DIR]:
        path.mkdir(parents=True, exist_ok=True)
    defaults = {
        CONFIG_DIR / "app.yaml": DEFAULT_APP,
        CONFIG_DIR / "risk.yaml": DEFAULT_RISK,
        CONFIG_DIR / "news.yaml": DEFAULT_NEWS,
        CONFIG_DIR / "perps.yaml": DEFAULT_PERPS,
        CONFIG_DIR / "dispatch.yaml": DEFAULT_DISPATCH,
        CONFIG_DIR / "strategy.yaml": DEFAULT_STRATEGY,
        CONFIG_DIR / "model.yaml": DEFAULT_MODEL,
        CONFIG_DIR / "workflow.yaml": DEFAULT_WORKFLOW,
    }
    for path, payload in defaults.items():
        if not path.exists():
            path.write_text(yaml.safe_dump(payload, sort_keys=False))
