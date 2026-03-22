from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openclaw_trader.config.models import QuantSettings
from openclaw_trader.config.loader import coerce_system_settings
from openclaw_trader.config.loader import load_coinbase_credentials, load_system_settings

from .helpers_v2 import build_test_settings


class ConfigLoaderTests(unittest.TestCase):
    def test_load_system_settings_reads_runtime_root_without_legacy_loader(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "config").mkdir(parents=True, exist_ok=True)
            (root / "state").mkdir(parents=True, exist_ok=True)
            (root / "secrets").mkdir(parents=True, exist_ok=True)
            (root / "config" / "app.yaml").write_text("bind_host: 0.0.0.0\nbind_port: 9999\n")
            (root / "config" / "risk.yaml").write_text(
                "\n".join(
                    [
                        "daily_loss_limit_pct_of_equity: 5.5",
                        "position_observe_drawdown_pct: 3.5",
                        "position_reduce_drawdown_pct: 6.5",
                        "position_exit_drawdown_pct: 9.5",
                        "max_live_orders_per_day: 7",
                    ]
                )
            )
            (root / "config" / "dispatch.yaml").write_text(
                "\n".join(
                    [
                        "scan_interval_seconds: 45",
                        "llm_fallback_minutes: 30",
                        "reply_channel: wecom-app",
                        "reply_to: user:test-owner",
                        "reply_account_id: default",
                        "timeout_seconds: 90",
                    ]
                )
            )
            (root / "config" / "model.yaml").write_text(
                "\n".join(
                    [
                        "enabled: true",
                        "interval: 15m",
                        "history_bars: 6000",
                        "forecast_horizon_bars: 4",
                        "min_confidence: 0.43",
                        "min_long_short_probability: 0.39",
                        "meta_min_confidence: 0.48",
                        "bootstrap_snapshot_exchange: binance_usdm",
                        "portfolio_same_theme_caution_share: 0.55",
                    ]
                )
            )
            (root / "config" / "perps.yaml").write_text(
                "\n".join(
                    [
                        "enabled: true",
                        "exchange: coinbase_intx",
                        "mode: live",
                        "coin: BTC",
                        "coins:",
                        "  - BTC",
                        "  - ETH",
                        "api_base: https://api.coinbase.com",
                        "paper_starting_equity_usd: 333.3",
                    ]
                )
            )
            (root / "config" / "strategy.yaml").write_text(
                "\n".join(
                    [
                        "daily_hours:",
                        "  - 9",
                        "  - 21",
                        "rewrite_cooldown_minutes: 25",
                        "probe_partial_scale: 0.6",
                        "rewrite_layers:",
                        "  - macro",
                        "  - exchange-status",
                    ]
                )
            )
            (root / "config" / "workflow.yaml").write_text(
                "\n".join(
                    [
                        "entry_mode: auto",
                        "signal_notify_cooldown_minutes: 50",
                        "owner_channel: wecom-app",
                        "owner_to: user:test",
                        "owner_account_id: default",
                        "fresh_news_minutes: 15",
                    ]
                )
            )
            (root / "config" / "agents.yaml").write_text(
                "\n".join(
                    [
                        "openclaw_enabled: true",
                        "pm_agent: pm-v2",
                        "risk_trader_agent: rt-v2",
                        "macro_event_analyst_agent: mea-v2",
                        "crypto_chief_agent: chief-v2",
                    ]
                )
            )
            (root / "config" / "news.yaml").write_text(
                "\n".join(
                    [
                        "poll_seconds: 300",
                        "sources:",
                        "  - id: feed-1",
                        "    type: rss",
                        "    url: https://example.com/feed.xml",
                    ]
                )
            )
            (root / "secrets" / "coinbase.env").write_text(
                "\n".join(
                    [
                        "COINBASE_API_KEY_ID=test-key",
                        "COINBASE_API_KEY_SECRET=test-secret",
                        "COINBASE_API_BASE=https://api.coinbase.com",
                    ]
                )
            )

            load_system_settings.cache_clear()
            with patch.dict("os.environ", {"OPENCLAW_V2_RUNTIME_ROOT": str(root)}, clear=False):
                settings = load_system_settings()
                credentials = load_coinbase_credentials(root)

            self.assertEqual(settings.app.bind_port, 9999)
            self.assertEqual(settings.quant.history_bars, 6000)
            self.assertEqual(settings.quant.forecast_horizons, {"1h": 4, "4h": 16, "12h": 48})
            self.assertEqual(settings.quant.bootstrap_snapshot_exchange, "binance_usdm")
            self.assertEqual(settings.quant.portfolio_same_theme_caution_share, 0.55)
            self.assertEqual(settings.risk.daily_loss_limit_pct_of_equity, 5.5)
            self.assertEqual(settings.risk.position_exit_drawdown_pct, 9.5)
            self.assertEqual(settings.execution.supported_coins, ["BTC", "ETH"])
            self.assertEqual(settings.execution.paper_starting_equity_usd, 333.3)
            self.assertEqual(settings.orchestrator.scan_interval_seconds, 45)
            self.assertEqual(settings.orchestrator.reply_to, "user:test-owner")
            self.assertEqual(settings.strategy.rewrite_cooldown_minutes, 25)
            self.assertEqual(settings.strategy.probe_partial_scale, 0.6)
            self.assertEqual(settings.workflow.entry_mode, "auto")
            self.assertEqual(settings.workflow.signal_notify_cooldown_minutes, 50)
            self.assertTrue(settings.agents.openclaw_enabled)
            self.assertEqual(settings.agents.pm_agent, "pm-v2")
            self.assertEqual(settings.agents.risk_trader_agent, "rt-v2")
            self.assertEqual(settings.agents.macro_event_analyst_agent, "mea-v2")
            self.assertEqual(settings.agents.crypto_chief_agent, "chief-v2")
            self.assertEqual(settings.news.sources[0].id, "feed-1")
            self.assertEqual(settings.coinbase.api_key_id, "test-key")
            self.assertEqual(credentials.api_key_secret, "test-secret")
            self.assertEqual(settings.paths.model_dir, root / "models")
            load_system_settings.cache_clear()

    def test_agent_settings_env_overrides_agents_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            (root / "config").mkdir(parents=True, exist_ok=True)
            (root / "state").mkdir(parents=True, exist_ok=True)
            (root / "secrets").mkdir(parents=True, exist_ok=True)
            for name in ["app", "risk", "dispatch", "model", "perps", "strategy", "workflow", "news"]:
                (root / "config" / f"{name}.yaml").write_text("{}\n")
            (root / "config" / "agents.yaml").write_text(
                "\n".join(
                    [
                        "openclaw_enabled: false",
                        "pm_agent: pm-yaml",
                    ]
                )
            )
            (root / "secrets" / "coinbase.env").write_text(
                "\n".join(
                    [
                        "COINBASE_API_KEY_ID=test-key",
                        "COINBASE_API_KEY_SECRET=test-secret",
                    ]
                )
            )

            load_system_settings.cache_clear()
            with patch.dict(
                "os.environ",
                {
                    "OPENCLAW_V2_RUNTIME_ROOT": str(root),
                    "OPENCLAW_V2_OPENCLAW_ENABLED": "true",
                    "OPENCLAW_V2_PM_AGENT": "pm-env",
                },
                clear=False,
            ):
                settings = load_system_settings()

            self.assertTrue(settings.agents.openclaw_enabled)
            self.assertEqual(settings.agents.pm_agent, "pm-env")
            load_system_settings.cache_clear()

    def test_coerce_system_settings_accepts_v2_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            settings = build_test_settings(Path(tempdir) / "state" / "test.db")
            coerced = coerce_system_settings(settings)
            self.assertIs(coerced, settings)

    def test_quant_settings_normalize_coin_horizon_interfaces(self) -> None:
        quant = QuantSettings(
            training_history_bars_overrides_by_coin_horizon={"eth:4H": 6000},
            target_move_threshold_pct_overrides_by_coin_horizon={"eth:4H": 0.003},
            probability_calibration_mode_by_coin_horizon={"eth:4H": " flat_isotonic_rescale "},
            coinalyze_api_key="  free-key  ",
            coinalyze_enabled=True,
            coinalyze_symbols_by_coin={"eth": "ETH_PERP.A"},
            acceptance_score_components_by_horizon={"4H": [" calibrated_top_probability ", "top_two_margin"]},
            acceptance_score_weights_by_coin_horizon={"eth:4H": {" calibrated_top_probability ": 0.7, "top_two_margin": 0.3}},
            regime_coverage_caps_by_coin_horizon={"eth:4H": {"bearish_breakdown": 0.08}},
            specialist_coin_horizons=["eth:4H"],
            historical_open_interest_source=" TARDIS ",
            tardis_api_key="  test-key  ",
            tardis_exchange="  binance-futures  ",
            history_backfill_days=12,
        )
        self.assertEqual(quant.training_history_bars_overrides_by_coin_horizon["ETH:4h"], 6000)
        self.assertEqual(quant.target_move_threshold_pct_overrides_by_coin_horizon["ETH:4h"], 0.003)
        self.assertEqual(quant.probability_calibration_mode_by_coin_horizon["ETH:4h"], "flat_isotonic_rescale")
        self.assertEqual(quant.coinalyze_api_key, "free-key")
        self.assertTrue(quant.coinalyze_enabled)
        self.assertEqual(quant.coinalyze_symbols_by_coin["ETH"], "ETH_PERP.A")
        self.assertEqual(quant.acceptance_score_components_by_horizon["4h"], ["calibrated_top_probability", "top_two_margin"])
        self.assertEqual(quant.acceptance_score_weights_by_coin_horizon["ETH:4h"]["top_two_margin"], 0.3)
        self.assertEqual(quant.regime_coverage_caps_by_coin_horizon["ETH:4h"]["bearish_breakdown"], 0.08)
        self.assertEqual(quant.specialist_coin_horizons, ["ETH:4h"])
        self.assertEqual(quant.historical_open_interest_source, "tardis")
        self.assertEqual(quant.tardis_api_key, "test-key")
        self.assertEqual(quant.tardis_exchange, "binance-futures")
        self.assertEqual(quant.history_backfill_days, 30)


if __name__ == "__main__":
    unittest.main()
