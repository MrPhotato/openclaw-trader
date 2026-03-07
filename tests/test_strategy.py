from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import openclaw_trader.strategy as strategy_module
from openclaw_trader.config import AppConfig, DispatchConfig, NewsConfig, PerpConfig, RiskConfig, RuntimeConfig, StrategyConfig, WorkflowConfig
from openclaw_trader.models import (
    AutopilotDecision,
    AutopilotPhase,
    Candle,
    EmergencyExitDecision,
    EntryWorkflowMode,
    NewsItem,
    PositionRiskStage,
    RiskProfile,
    SignalDecision,
    SignalSide,
)
from openclaw_trader.state import StateStore
from openclaw_trader.strategy import (
    _format_share_range,
    _perp_recommended_limits,
    build_strategy_memory_perps,
    parse_strategy_response,
    routine_refresh_due,
    save_strategy_doc,
    strategy_due_today,
    strategy_rewrite_due_by_news,
    strategy_rewrite_reason,
    strategy_update_is_material,
)


class FakePerpEngine:
    def candles(self, coin: str | None = None, interval: str = "15m", lookback: int = 48) -> list[Candle]:
        now = datetime(2026, 3, 5, 0, 0, tzinfo=UTC)
        interval_seconds = {
            "15m": 900,
            "1h": 3600,
            "1d": 86400,
        }.get(interval, 900)
        candles: list[Candle] = []
        base = Decimal("100")
        for index in range(lookback):
            offset = lookback - index
            start = int((now - timedelta(seconds=offset * interval_seconds)).timestamp())
            open_price = base + Decimal(str(index))
            close_price = open_price + Decimal("1")
            candles.append(
                Candle(
                    start=start,
                    open=open_price,
                    close=close_price,
                    high=close_price + Decimal("1"),
                    low=open_price - Decimal("1"),
                    volume=Decimal("10"),
                )
            )
        return candles


class FakeSupervisor:
    def __init__(self) -> None:
        self.engine = FakePerpEngine()


class StrategyTests(unittest.TestCase):
    def test_strategy_module_exports_expected_public_api(self) -> None:
        expected_names = [
            "STRATEGY_INPUT_JSON",
            "STRATEGY_INPUT_MD",
            "STRATEGY_MEMORY_JSON",
            "STRATEGY_MEMORY_MD",
            "STRATEGY_DAY_JSON",
            "STRATEGY_DAY_MD",
            "STRATEGY_HISTORY_JSONL",
            "POSITION_JOURNAL_JSONL",
            "STRATEGY_CHANGE_LOG_JSONL",
            "build_strategy_memory_perps",
            "build_strategy_input",
            "build_strategy_input_perps",
            "parse_strategy_response",
            "load_current_strategy",
            "save_strategy_doc",
            "routine_refresh_due",
            "strategy_due_today",
            "strategy_rewrite_due_by_news",
            "strategy_rewrite_reason",
            "scheduled_recheck_reason",
            "strategy_update_is_material",
        ]
        for name in expected_names:
            self.assertTrue(hasattr(strategy_module, name), name)

    def test_perp_recommended_limits_use_target_share_ranges(self) -> None:
        strategy = StrategyConfig()
        weak = _perp_recommended_limits(
            {
                "signal": {"side": "short", "confidence": 0.65},
                "risk": {"position_risk_stage": "normal"},
                "minimum_actionable_share_pct_of_exposure_budget": 0.0,
            },
            strategy,
        )
        medium = _perp_recommended_limits(
            {
                "signal": {"side": "short", "confidence": 0.75},
                "risk": {"position_risk_stage": "normal"},
                "minimum_actionable_share_pct_of_exposure_budget": 0.0,
            },
            strategy,
        )
        strong = _perp_recommended_limits(
            {
                "signal": {"side": "short", "confidence": 0.90},
                "risk": {"position_risk_stage": "normal"},
                "minimum_actionable_share_pct_of_exposure_budget": 0.0,
            },
            strategy,
        )
        self.assertEqual(weak["target_position_share_range_pct"], {"min": 10.0, "max": 20.0})
        self.assertEqual(medium["target_position_share_range_pct"], {"min": 20.0, "max": 40.0})
        self.assertEqual(strong["target_position_share_range_pct"], {"min": 40.0, "max": 60.0})
        self.assertEqual(weak["target_position_share_pct"], 15.0)
        self.assertEqual(medium["target_position_share_pct"], 30.0)
        self.assertEqual(strong["target_position_share_pct"], 50.0)
        self.assertEqual(_format_share_range(medium["target_position_share_range_pct"]["min"], medium["target_position_share_range_pct"]["max"]), "20.0%-40.0%")

    def test_perp_recommended_limits_marks_true_flat_context(self) -> None:
        strategy = StrategyConfig()
        flat = _perp_recommended_limits(
            {
                "signal": {
                    "side": "flat",
                    "confidence": 0.98,
                    "metadata": {"prob_short": 0.01, "prob_long": 0.01},
                },
                "risk": {"position_risk_stage": "normal"},
                "minimum_actionable_share_pct_of_exposure_budget": 0.0,
            },
            strategy,
        )
        self.assertEqual(flat["signal_context"], "true_flat")
        self.assertIsNone(flat["signal_direction_hint"])
        self.assertEqual(flat["target_position_share_range_pct"], {"min": 0.0, "max": 0.0})
        self.assertIn("真 flat", flat["reason"])

    def test_perp_recommended_limits_marks_breakout_watch_context(self) -> None:
        strategy = StrategyConfig()
        flat = _perp_recommended_limits(
            {
                "signal": {
                    "side": "flat",
                    "confidence": 0.72,
                    "metadata": {"prob_short": 0.31, "prob_long": 0.12},
                },
                "risk": {"position_risk_stage": "normal"},
                "minimum_actionable_share_pct_of_exposure_budget": 0.0,
            },
            strategy,
        )
        self.assertEqual(flat["signal_context"], "breakout_watch")
        self.assertEqual(flat["signal_direction_hint"], "short")
        self.assertIn("breakout_watch", flat["reason"])

    def test_parse_strategy_response_extracts_json(self) -> None:
        text = '好的，以下是结果：{"strategy_date":"2026-03-03","market_regime":"trend","risk_mode":"normal","soft_max_leverage":3,"summary":"偏多","invalidators":["交易所高危状态"],"symbols":[{"symbol":"BTC","bias":"long","max_position_share_pct":60,"max_order_share_pct":25,"thesis":"趋势延续"}]}'
        payload = parse_strategy_response(
            text,
            now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC),
            strategy_date="2026-03-03",
            reason="daily_strategy_due",
        )
        self.assertEqual(payload["market_regime"], "trend")
        self.assertEqual(payload["symbols"][0]["symbol"], "BTC")
        self.assertEqual(payload["soft_min_leverage"], 1.0)
        self.assertEqual(payload["soft_max_leverage"], 3.0)
        self.assertNotIn("soft_total_exposure_pct", payload)

    def test_parse_strategy_response_defaults_missing_risk_mode_to_aggressive(self) -> None:
        text = '{"strategy_date":"2026-03-03","market_regime":"trend","summary":"偏多","invalidators":[],"symbols":[{"symbol":"BTC-PERP","bias":"long","max_position_share_pct":20,"max_order_share_pct":8,"thesis":"趋势延续"}]}'
        payload = parse_strategy_response(
            text,
            now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC),
            strategy_date="2026-03-03",
            reason="daily_strategy_due",
            allowed_symbols={"BTC-PERP"},
        )
        self.assertEqual(payload["risk_mode"], "aggressive")

    def test_parse_strategy_response_clamps_soft_leverage_range_with_hard_floor(self) -> None:
        text = '{"strategy_date":"2026-03-03","market_regime":"trend","risk_mode":"normal","soft_min_leverage":0.4,"soft_max_leverage":0.6,"summary":"偏多","invalidators":[],"symbols":[{"symbol":"BTC-PERP","bias":"long","max_position_share_pct":20,"max_order_share_pct":8,"thesis":"趋势延续"}]}'
        payload = parse_strategy_response(
            text,
            now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC),
            strategy_date="2026-03-03",
            reason="daily_strategy_due",
            allowed_symbols={"BTC-PERP"},
            recommended_limits={
                "__meta__": {"hard_max_leverage": 5.0},
            },
        )
        self.assertEqual(payload["soft_min_leverage"], 1.0)
        self.assertEqual(payload["soft_max_leverage"], 1.0)

    def test_parse_strategy_response_filters_untracked_symbols(self) -> None:
        text = '{"strategy_date":"2026-03-03","market_regime":"trend","risk_mode":"normal","summary":"偏多","invalidators":[],"symbols":[{"symbol":"BTC-PERP","bias":"long","max_position_share_pct":60,"max_order_share_pct":25,"thesis":"趋势延续"},{"symbol":"BTC-USDC","bias":"neutral","max_position_share_pct":5,"max_order_share_pct":3,"thesis":"忽略"}]}'
        payload = parse_strategy_response(
            text,
            now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC),
            strategy_date="2026-03-03",
            reason="daily_strategy_due",
            allowed_symbols={"BTC-PERP", "ETH-PERP"},
        )
        self.assertEqual([item["symbol"] for item in payload["symbols"]], ["BTC-PERP"])

    def test_parse_strategy_response_keeps_intx_symbol_when_allowed_symbol_is_perp(self) -> None:
        text = '{"strategy_date":"2026-03-03","market_regime":"trend","risk_mode":"normal","summary":"偏多","invalidators":[],"symbols":[{"symbol":"BTC-PERP-INTX","bias":"long","max_position_share_pct":60,"max_order_share_pct":25,"thesis":"趋势延续"}]}'
        payload = parse_strategy_response(
            text,
            now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC),
            strategy_date="2026-03-03",
            reason="daily_strategy_due",
            allowed_symbols={"BTC-PERP"},
            recommended_limits={
                "BTC-PERP": {"max_position_share_pct": 14.0, "max_order_share_pct": 6.0},
            },
        )
        self.assertEqual(payload["symbols"][0]["symbol"], "BTC-PERP")
        self.assertEqual(payload["symbols"][0]["max_position_share_pct"], 60.0)

    def test_parse_strategy_response_uses_recommended_limits_as_fallback_only(self) -> None:
        text = '{"strategy_date":"2026-03-03","market_regime":"trend","risk_mode":"normal","soft_max_leverage":9,"summary":"偏多","invalidators":[],"watchlist_suggestions":{"add":["SOL"],"remove":["DOGE"],"reason":"只保留主流资产"},"symbols":[{"symbol":"BTC-PERP","bias":"long","max_position_share_pct":60,"max_order_share_pct":25,"thesis":"趋势延续"},{"symbol":"ETH-PERP","bias":"long","max_position_share_pct":0,"max_order_share_pct":0,"thesis":"等待确认"}]}'
        payload = parse_strategy_response(
            text,
            now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC),
            strategy_date="2026-03-03",
            reason="major_news:macro",
            allowed_symbols={"BTC-PERP", "ETH-PERP"},
            recommended_limits={
                "BTC-PERP": {"max_position_share_pct": 14.0, "max_order_share_pct": 6.0},
                "ETH-PERP": {"max_position_share_pct": 8.0, "max_order_share_pct": 4.0},
                "__meta__": {"hard_total_exposure_pct": 100.0, "hard_max_leverage": 5.0},
            },
        )
        self.assertEqual(
            payload["symbols"],
            [
                {"symbol": "BTC-PERP", "bias": "long", "max_position_share_pct": 60.0, "max_order_share_pct": 25.0, "thesis": "趋势延续"},
                {"symbol": "ETH-PERP", "bias": "long", "max_position_share_pct": 8.0, "max_order_share_pct": 4.0, "thesis": "等待确认"},
            ],
        )
        self.assertEqual(payload["soft_max_leverage"], 5.0)
        self.assertNotIn("soft_total_exposure_pct", payload)
        self.assertEqual(payload["watchlist_suggestions"]["add"], ["SOL"])

    def test_parse_strategy_response_forces_neutral_and_avoid_to_zero(self) -> None:
        text = '{"strategy_date":"2026-03-03","market_regime":"trend","risk_mode":"normal","summary":"偏多","invalidators":[],"symbols":[{"symbol":"BTC-PERP","bias":"neutral","max_position_share_pct":12,"max_order_share_pct":6,"thesis":"观望"},{"symbol":"ETH-PERP","bias":"avoid","max_position_share_pct":20,"max_order_share_pct":10,"thesis":"规避"}]}'
        payload = parse_strategy_response(
            text,
            now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC),
            strategy_date="2026-03-03",
            reason="daily_strategy_due",
            allowed_symbols={"BTC-PERP", "ETH-PERP"},
        )
        self.assertEqual(
            payload["symbols"],
            [
                {"symbol": "BTC-PERP", "bias": "neutral", "max_position_share_pct": 0.0, "max_order_share_pct": 0.0, "thesis": "观望"},
                {"symbol": "ETH-PERP", "bias": "avoid", "max_position_share_pct": 0.0, "max_order_share_pct": 0.0, "thesis": "规避"},
            ],
        )

    def test_parse_strategy_response_zeroes_non_actionable_small_target(self) -> None:
        text = '{"strategy_date":"2026-03-03","market_regime":"trend","risk_mode":"normal","soft_max_leverage":1,"summary":"偏空","invalidators":[],"symbols":[{"symbol":"BTC-PERP","bias":"short","max_position_share_pct":4,"max_order_share_pct":4,"thesis":"轻量空头仓位"}]}'
        payload = parse_strategy_response(
            text,
            now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC),
            strategy_date="2026-03-03",
            reason="daily_strategy_due",
            allowed_symbols={"BTC-PERP"},
            recommended_limits={
                "BTC-PERP": {
                    "max_position_share_pct": 14.0,
                    "max_order_share_pct": 6.0,
                    "minimum_trade_notional_usd": 10.0,
                },
                "__meta__": {
                    "hard_total_exposure_pct": 100.0,
                    "hard_max_leverage": 5.0,
                    "portfolio_total_equity_usd": 200.0,
                },
            },
        )
        self.assertEqual(
            payload["symbols"],
            [
                {"symbol": "BTC-PERP", "bias": "short", "max_position_share_pct": 0.0, "max_order_share_pct": 0.0, "thesis": "轻量空头仓位"},
            ],
        )

    def test_parse_strategy_response_keeps_actionable_target_with_higher_soft_leverage(self) -> None:
        text = '{"strategy_date":"2026-03-03","market_regime":"trend","risk_mode":"normal","soft_max_leverage":5,"summary":"偏空","invalidators":[],"symbols":[{"symbol":"BTC-PERP","bias":"short","max_position_share_pct":4,"max_order_share_pct":4,"thesis":"轻量空头仓位"}]}'
        payload = parse_strategy_response(
            text,
            now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC),
            strategy_date="2026-03-03",
            reason="daily_strategy_due",
            allowed_symbols={"BTC-PERP"},
            recommended_limits={
                "BTC-PERP": {
                    "max_position_share_pct": 14.0,
                    "max_order_share_pct": 6.0,
                    "minimum_trade_notional_usd": 10.0,
                },
                "__meta__": {
                    "hard_total_exposure_pct": 100.0,
                    "hard_max_leverage": 5.0,
                    "portfolio_total_equity_usd": 200.0,
                },
            },
        )
        self.assertEqual(
            payload["symbols"],
            [
                {"symbol": "BTC-PERP", "bias": "short", "max_position_share_pct": 4.0, "max_order_share_pct": 4.0, "thesis": "轻量空头仓位"},
            ],
        )

    def test_parse_strategy_response_keeps_scheduled_rechecks(self) -> None:
        text = '{"strategy_date":"2026-03-03","market_regime":"trend","risk_mode":"normal","summary":"偏多","invalidators":[],"scheduled_rechecks":[{"fingerprint":"fomc-2026-03-19","event_at":"2026-03-19T02:00:00+00:00","run_at":"2026-03-19T01:00:00+00:00","reason":"T-1h FOMC final review"}],"symbols":[{"symbol":"BTC-PERP","bias":"long","max_position_share_pct":20,"max_order_share_pct":8,"thesis":"趋势延续"}]}'
        payload = parse_strategy_response(
            text,
            now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC),
            strategy_date="2026-03-03",
            reason="major_news:fomc",
            allowed_symbols={"BTC-PERP"},
        )
        self.assertEqual(len(payload["scheduled_rechecks"]), 1)
        self.assertEqual(payload["scheduled_rechecks"][0]["fingerprint"], "fomc-2026-03-19")

    def test_parse_strategy_response_rejects_non_strategy_json(self) -> None:
        text = '{"decision":"reject","reason":"not strategy","orders":[]}'
        with self.assertRaisesRegex(ValueError, "missing market_regime"):
            parse_strategy_response(
                text,
                now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC),
                strategy_date="2026-03-03",
                reason="manual_refresh",
                allowed_symbols={"BTC-PERP"},
            )

    def test_parse_strategy_response_rejects_invalid_bias(self) -> None:
        text = '{"strategy_date":"2026-03-03","market_regime":"trend","risk_mode":"normal","summary":"偏多","invalidators":[],"symbols":[{"symbol":"BTC-PERP","bias":"bullish","max_position_share_pct":20,"max_order_share_pct":8,"thesis":"趋势延续"}]}'
        with self.assertRaisesRegex(ValueError, "invalid bias"):
            parse_strategy_response(
                text,
                now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC),
                strategy_date="2026-03-03",
                reason="daily_strategy_due",
                allowed_symbols={"BTC-PERP"},
            )

    def test_parse_strategy_response_preserves_future_rechecks_when_omitted(self) -> None:
        text = '{"strategy_date":"2026-03-03","market_regime":"trend","risk_mode":"normal","summary":"偏多","invalidators":[],"symbols":[{"symbol":"BTC-PERP","bias":"long","max_position_share_pct":20,"max_order_share_pct":8,"thesis":"趋势延续"}]}'
        payload = parse_strategy_response(
            text,
            now=datetime(2026, 3, 3, 1, 0, tzinfo=UTC),
            strategy_date="2026-03-03",
            reason="major_news:fomc",
            allowed_symbols={"BTC-PERP"},
            current_strategy={
                "scheduled_rechecks": [
                    {
                        "fingerprint": "fomc-2026-03-19",
                        "event_at": "2026-03-19T02:00:00+00:00",
                        "run_at": "2026-03-19T01:00:00+00:00",
                        "reason": "T-1h FOMC final review",
                    }
                ]
            },
        )
        self.assertEqual(len(payload["scheduled_rechecks"]), 1)
        self.assertEqual(payload["scheduled_rechecks"][0]["reason"], "T-1h FOMC final review")

    def test_save_strategy_doc_increments_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy_json = Path(tmpdir) / "strategy-day.json"
            strategy_md = Path(tmpdir) / "strategy-day.md"
            strategy_history = Path(tmpdir) / "strategy-history.jsonl"
            strategy_change_log = Path(tmpdir) / "strategy-change-log.jsonl"
            with patch("openclaw_trader.strategy.STRATEGY_DAY_JSON", strategy_json), \
                 patch("openclaw_trader.strategy.STRATEGY_DAY_MD", strategy_md), \
                 patch("openclaw_trader.strategy.STRATEGY_HISTORY_JSONL", strategy_history), \
                 patch("openclaw_trader.strategy.STRATEGY_CHANGE_LOG_JSONL", strategy_change_log):
                first = save_strategy_doc(
                    {
                        "strategy_date": "2026-03-03",
                        "change_reason": "daily_strategy_due",
                        "market_regime": "trend",
                        "risk_mode": "normal",
                        "soft_max_leverage": 3,
                        "summary": "偏多",
                        "invalidators": [],
                        "watchlist_suggestions": {"add": [], "remove": [], "reason": ""},
                        "symbols": [{"symbol": "BTC", "bias": "long", "max_position_share_pct": 60, "max_order_share_pct": 25, "thesis": "趋势延续"}],
                    },
                    datetime(2026, 3, 3, 1, 0, tzinfo=UTC),
                )
                second = save_strategy_doc(
                    {
                        "strategy_date": "2026-03-03",
                        "change_reason": "major_news:fed",
                        "market_regime": "risk-off",
                        "risk_mode": "defensive",
                        "soft_max_leverage": 2,
                        "summary": "风险收缩",
                        "invalidators": [],
                        "watchlist_suggestions": {"add": ["SOL"], "remove": [], "reason": "关注轮动"},
                        "symbols": [{"symbol": "BTC", "bias": "avoid", "max_position_share_pct": 20, "max_order_share_pct": 10, "thesis": "等待波动回落"}],
                    },
                    datetime(2026, 3, 3, 2, 0, tzinfo=UTC),
                )
            self.assertEqual(first["version"], 1)
            self.assertEqual(second["version"], 2)
            self.assertTrue(strategy_md.exists())
            self.assertEqual(len(strategy_history.read_text().splitlines()), 2)
            self.assertEqual(len(strategy_change_log.read_text().splitlines()), 2)
            self.assertNotIn("soft_total_exposure_pct", json.loads(strategy_json.read_text()))
            self.assertNotIn("软总敞口上限", strategy_md.read_text())

    def test_strategy_due_and_rewrite_by_news(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "state.db")
            strategy = StrategyConfig(daily_hours=[9, 21], timezone="Asia/Shanghai")
            now = datetime(2026, 3, 3, 13, 30, tzinfo=UTC)
            self.assertTrue(strategy_due_today(store, strategy, now))
            store.set_value("strategy:last_strategy_slot", "2026-03-03@21")
            self.assertFalse(strategy_due_today(store, strategy, now))
            self.assertTrue(routine_refresh_due(store, strategy, now))
            store.set_value("strategy:last_strategy_date", "2026-03-03")
            self.assertFalse(routine_refresh_due(store, strategy, now))
            store.set_value("strategy:last_updated_at", datetime(2026, 3, 3, 1, 0, tzinfo=UTC).isoformat())
            news = [
                NewsItem(
                    source="fed-press-monetary",
                    title="FOMC statement",
                    url="https://example.com/fomc",
                    layer="macro",
                    severity="high",
                )
            ]
            self.assertTrue(strategy_rewrite_due_by_news(store, strategy, news, now))
            store.set_value("strategy:last_news_fingerprint", "fed-press-monetary|FOMC statement|https://example.com/fomc")
            self.assertFalse(strategy_rewrite_due_by_news(store, strategy, news, now))

    def test_strategy_rewrite_reason_on_regime_shift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "state.db")
            store.set_value("strategy:last_updated_at", datetime(2026, 3, 3, 0, 0, tzinfo=UTC).isoformat())
            strategy = StrategyConfig(regime_shift_confirmation_minutes=15, regime_shift_confirmation_rounds=3)
            decision = AutopilotDecision(
                phase=AutopilotPhase.observe,
                notify_user=True,
                reason="fresh_relevant_news_requires_observation",
                product_id="BTC-PERP",
                flow_mode=EntryWorkflowMode.auto,
                signal=SignalDecision(
                    product_id="BTC-PERP",
                    side=SignalSide.short,
                    confidence=0.8,
                    reason="trend down",
                    risk_profile=RiskProfile.normal,
                    metadata={"regime": "bearish_breakdown"},
                ),
                panic=EmergencyExitDecision(
                    should_exit=False,
                    reason="ok",
                    position_risk_stage=PositionRiskStage.normal,
                ),
            )
            first = strategy_rewrite_reason(
                store,
                strategy,
                current_strategy={"market_regime": "neutral_consolidation", "risk_mode": "normal"},
                decision=decision,
                now=datetime(2026, 3, 3, 2, 0, tzinfo=UTC),
            )
            self.assertIsNone(first)
            second = strategy_rewrite_reason(
                store,
                strategy,
                current_strategy={"market_regime": "neutral_consolidation", "risk_mode": "normal"},
                decision=decision,
                now=datetime(2026, 3, 3, 2, 10, tzinfo=UTC),
            )
            self.assertIsNone(second)
            reason = strategy_rewrite_reason(
                store,
                strategy,
                current_strategy={"market_regime": "neutral_consolidation", "risk_mode": "normal"},
                decision=decision,
                now=datetime(2026, 3, 3, 2, 16, tzinfo=UTC),
            )
            self.assertEqual(reason, "regime_shift:bearish_breakdown")

    def test_strategy_rewrite_reason_applies_regime_shift_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "state.db")
            store.set_value("strategy:last_updated_at", datetime(2026, 3, 3, 0, 0, tzinfo=UTC).isoformat())
            store.set_value("strategy:last_regime_shift_rewrite_at", datetime(2026, 3, 3, 1, 0, tzinfo=UTC).isoformat())
            strategy = StrategyConfig(
                regime_shift_confirmation_minutes=0,
                regime_shift_confirmation_rounds=1,
                regime_shift_rewrite_cooldown_minutes=180,
            )
            decision = AutopilotDecision(
                phase=AutopilotPhase.observe,
                notify_user=True,
                reason="exchange_status_requires_observation",
                product_id="BTC-PERP",
                flow_mode=EntryWorkflowMode.auto,
                signal=SignalDecision(
                    product_id="BTC-PERP",
                    side=SignalSide.short,
                    confidence=0.8,
                    reason="trend down",
                    risk_profile=RiskProfile.normal,
                    metadata={"regime": "bearish_breakdown"},
                ),
            )
            blocked = strategy_rewrite_reason(
                store,
                strategy,
                current_strategy={"market_regime": "neutral_consolidation", "risk_mode": "normal"},
                decision=decision,
                now=datetime(2026, 3, 3, 2, 0, tzinfo=UTC),
            )
            self.assertIsNone(blocked)
            allowed = strategy_rewrite_reason(
                store,
                strategy,
                current_strategy={"market_regime": "neutral_consolidation", "risk_mode": "normal"},
                decision=decision,
                now=datetime(2026, 3, 3, 4, 1, tzinfo=UTC),
            )
            self.assertEqual(allowed, "regime_shift:bearish_breakdown")

    def test_strategy_rewrite_reason_on_panic_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "state.db")
            store.set_value("strategy:last_updated_at", datetime(2026, 3, 3, 0, 0, tzinfo=UTC).isoformat())
            strategy = StrategyConfig()
            decision = AutopilotDecision(
                phase=AutopilotPhase.panic_exit,
                notify_user=True,
                reason="risk_layer_approved_emergency_exit",
                product_id="ETH-PERP",
                flow_mode=EntryWorkflowMode.auto,
                panic=EmergencyExitDecision(
                    should_exit=True,
                    reason="approved_emergency_exit",
                    position_drawdown_pct=11.2,
                    position_risk_stage=PositionRiskStage.exit,
                ),
            )
            reason = strategy_rewrite_reason(
                store,
                strategy,
                current_strategy={"market_regime": "neutral_consolidation", "risk_mode": "normal"},
                decision=decision,
                now=datetime(2026, 3, 3, 2, 0, tzinfo=UTC),
            )
            self.assertEqual(reason, "risk_shift:panic_exit")

    def test_strategy_rewrite_reason_ignores_non_panic_risk_shift(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "state.db")
            store.set_value("strategy:last_updated_at", datetime(2026, 3, 3, 0, 0, tzinfo=UTC).isoformat())
            strategy = StrategyConfig()
            decision = AutopilotDecision(
                phase=AutopilotPhase.observe,
                notify_user=True,
                reason="position_drawdown_requires_attention",
                product_id="ETH-PERP",
                flow_mode=EntryWorkflowMode.auto,
                panic=EmergencyExitDecision(
                    should_exit=False,
                    reason="observe",
                    position_drawdown_pct=4.2,
                    position_risk_stage=PositionRiskStage.observe,
                ),
            )
            reason = strategy_rewrite_reason(
                store,
                strategy,
                current_strategy={"market_regime": "neutral_consolidation", "risk_mode": "normal"},
                decision=decision,
                now=datetime(2026, 3, 3, 2, 0, tzinfo=UTC),
            )
            self.assertIsNone(reason)

    def test_strategy_rewrite_ignores_irrelevant_exchange_status_noise(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "state.db")
            store.set_value("strategy:last_updated_at", datetime(2026, 3, 3, 0, 0, tzinfo=UTC).isoformat())
            strategy = StrategyConfig()
            news = [
                NewsItem(
                    source="coinbase-status",
                    title="Base App & Wallet Extension Performance - Bitcoin Transactions",
                    url="https://status.coinbase.com/incidents/example",
                    summary="Investigating degraded performance for wallet-extension bitcoin transactions.",
                    layer="exchange-status",
                    severity="medium",
                )
            ]
            self.assertFalse(
                strategy_rewrite_due_by_news(
                    store,
                    strategy,
                    news,
                    datetime(2026, 3, 3, 2, 0, tzinfo=UTC),
                )
            )
            decision = AutopilotDecision(
                phase=AutopilotPhase.observe,
                notify_user=True,
                reason="exchange_status_requires_observation",
                product_id="BTC-PERP",
                flow_mode=EntryWorkflowMode.auto,
                latest_news=news,
            )
            reason = strategy_rewrite_reason(
                store,
                strategy,
                current_strategy={"market_regime": "neutral_consolidation", "risk_mode": "normal"},
                decision=decision,
                now=datetime(2026, 3, 3, 2, 0, tzinfo=UTC),
            )
            self.assertIsNone(reason)

    def test_strategy_rewrite_accepts_derivatives_exchange_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "state.db")
            store.set_value("strategy:last_updated_at", datetime(2026, 3, 3, 0, 0, tzinfo=UTC).isoformat())
            strategy = StrategyConfig()
            news = [
                NewsItem(
                    source="coinbase-status",
                    title="International Exchange derivatives matching engine degraded",
                    url="https://status.coinbase.com/incidents/intx-example",
                    summary="Investigating degraded service for perpetual order matching on the international exchange.",
                    layer="exchange-status",
                    severity="high",
                )
            ]
            self.assertTrue(
                strategy_rewrite_due_by_news(
                    store,
                    strategy,
                    news,
                    datetime(2026, 3, 3, 2, 0, tzinfo=UTC),
                )
            )
            decision = AutopilotDecision(
                phase=AutopilotPhase.observe,
                notify_user=True,
                reason="exchange_status_requires_observation",
                product_id="BTC-PERP",
                flow_mode=EntryWorkflowMode.auto,
                latest_news=news,
            )
            reason = strategy_rewrite_reason(
                store,
                strategy,
                current_strategy={"market_regime": "neutral_consolidation", "risk_mode": "normal"},
                decision=decision,
                now=datetime(2026, 3, 3, 2, 0, tzinfo=UTC),
            )
            self.assertEqual(reason, "major_news:coinbase-status")

    def test_strategy_rewrite_reason_bypasses_cooldown_for_high_exchange_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "state.db")
            store.set_value("strategy:last_updated_at", datetime(2026, 3, 3, 1, 50, tzinfo=UTC).isoformat())
            strategy = StrategyConfig(rewrite_cooldown_minutes=30)
            decision = AutopilotDecision(
                phase=AutopilotPhase.observe,
                notify_user=True,
                reason="exchange_status_requires_observation",
                product_id="BTC-PERP",
                flow_mode=EntryWorkflowMode.auto,
                latest_news=[
                    NewsItem(
                        source="hyperliquid-status",
                        title="Matching engine incident",
                        url="https://example.com/status",
                        layer="exchange-status",
                        severity="high",
                    )
                ],
            )
            reason = strategy_rewrite_reason(
                store,
                strategy,
                current_strategy={"market_regime": "neutral_consolidation", "risk_mode": "normal"},
                decision=decision,
                now=datetime(2026, 3, 3, 2, 0, tzinfo=UTC),
            )
            self.assertEqual(reason, "major_news:hyperliquid-status")

    def test_strategy_update_is_material_ignores_small_size_jitter(self) -> None:
        strategy = StrategyConfig(
            material_position_change_pct=2.0,
            material_order_change_pct=1.0,
            material_leverage_change=0.25,
        )
        previous = {
            "market_regime": "bearish_breakdown",
            "risk_mode": "defensive",
            "soft_max_leverage": 1.0,
            "invalidators": ["a", "b"],
            "symbols": [
                {"symbol": "BTC-PERP", "bias": "short", "max_position_share_pct": 20.0, "max_order_share_pct": 8.0},
                {"symbol": "ETH-PERP", "bias": "short", "max_position_share_pct": 10.0, "max_order_share_pct": 4.0},
            ],
        }
        current = {
            "market_regime": "bearish_breakdown",
            "risk_mode": "defensive",
            "soft_max_leverage": 1.1,
            "invalidators": ["b", "a"],
            "symbols": [
                {"symbol": "BTC-PERP", "bias": "short", "max_position_share_pct": 21.0, "max_order_share_pct": 8.5},
                {"symbol": "ETH-PERP", "bias": "short", "max_position_share_pct": 10.0, "max_order_share_pct": 4.0},
            ],
        }
        self.assertFalse(strategy_update_is_material(previous, current, strategy, reason="regime_shift:bearish_breakdown"))

    def test_strategy_update_is_material_detects_bias_or_size_shift(self) -> None:
        strategy = StrategyConfig(
            material_position_change_pct=2.0,
            material_order_change_pct=1.0,
            material_leverage_change=0.25,
        )
        previous = {
            "market_regime": "bearish_breakdown",
            "risk_mode": "defensive",
            "soft_max_leverage": 1.0,
            "invalidators": ["a", "b"],
            "symbols": [
                {"symbol": "ETH-PERP", "bias": "short", "max_position_share_pct": 10.0, "max_order_share_pct": 4.0},
            ],
        }
        current = {
            "market_regime": "bearish_breakdown",
            "risk_mode": "defensive",
            "soft_max_leverage": 1.0,
            "invalidators": ["a", "b"],
            "symbols": [
                {"symbol": "ETH-PERP", "bias": "short", "max_position_share_pct": 13.0, "max_order_share_pct": 4.0},
            ],
        }
        self.assertTrue(strategy_update_is_material(previous, current, strategy, reason="regime_shift:bearish_breakdown"))
        self.assertTrue(strategy_update_is_material(previous, current, strategy, reason="risk_shift:panic_exit"))

    def test_build_strategy_memory_perps_writes_position_order_and_curve_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "state.db")
            store.record_perp_paper_fill(
                exchange="coinbase_intx",
                coin="BTC",
                action="open_live",
                side="long",
                notional_usd="50",
                leverage="1",
                price="101",
                realized_pnl_usd=None,
                payload={
                    "fills": [
                        {
                            "trade_time": "2026-03-04T17:01:00+00:00",
                            "product_id": "BTC-PERP-INTX",
                            "order_id": "order-1",
                            "size": "0.5",
                            "commission": "0.1",
                            "price": "101",
                        }
                    ]
                },
            )
            history_path = Path(tmpdir) / "strategy-history.jsonl"
            history_path.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "version": 1,
                                "updated_at": "2026-03-04T15:00:00+00:00",
                                "change_reason": "daily_strategy_due",
                                "market_regime": "bullish_trend",
                                "risk_mode": "normal",
                                "symbols": [
                                    {
                                        "symbol": "BTC-PERP",
                                        "bias": "long",
                                        "max_position_share_pct": 20,
                                        "max_order_share_pct": 8,
                                        "thesis": "trend",
                                    }
                                ],
                            }
                        ),
                        json.dumps(
                            {
                                "version": 2,
                                "updated_at": "2026-03-04T16:30:00+00:00",
                                "change_reason": "major_news:macro",
                                "market_regime": "neutral_consolidation",
                                "risk_mode": "defensive",
                                "symbols": [
                                    {
                                        "symbol": "BTC-PERP",
                                        "bias": "neutral",
                                        "max_position_share_pct": 0,
                                        "max_order_share_pct": 0,
                                        "thesis": "wait",
                                    }
                                ],
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )
            runtime = RuntimeConfig(
                app=AppConfig(),
                risk=RiskConfig(),
                news=NewsConfig(),
                perps=PerpConfig(exchange="coinbase_intx", coins=["BTC"]),
                dispatch=DispatchConfig(),
                strategy=StrategyConfig(),
                workflow=WorkflowConfig(),
            )
            memory_json = Path(tmpdir) / "strategy-memory.json"
            memory_md = Path(tmpdir) / "strategy-memory.md"
            position_journal = Path(tmpdir) / "position-journal.jsonl"
            strategy_change_log = Path(tmpdir) / "strategy-change-log.jsonl"
            position_journal.write_text(
                json.dumps(
                    {
                        "journaled_at": "2026-03-04T23:00:00+00:00",
                        "product_id": "BTC-PERP",
                        "success": True,
                        "strategy_version": 2,
                        "approved_plan": {"action": "reduce", "side": "long", "notional_usd": "10", "margin_usd": "5", "execution_leverage": "2"},
                        "review": {"stop_loss_price": "98", "take_profit_price": "114", "exit_plan": "跌回区间下沿就继续减仓"},
                        "before_position": {"side": "long", "notional_usd": "50"},
                        "after_position": {"side": "long", "notional_usd": "40"},
                        "decision_reason": "strategy_target_requires_reduction",
                        "review_reason": "lock in",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            strategy_change_log.write_text(
                json.dumps(
                    {
                        "journaled_at": "2026-03-04T21:30:00+00:00",
                        "from_version": 1,
                        "to_version": 2,
                        "change_reason": "major_news:macro",
                        "market_regime_from": "bullish_trend",
                        "market_regime_to": "neutral_consolidation",
                        "risk_mode_from": "normal",
                        "risk_mode_to": "defensive",
                        "summary_to": "wait",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch("openclaw_trader.strategy.STRATEGY_HISTORY_JSONL", history_path), \
                 patch("openclaw_trader.strategy.STRATEGY_MEMORY_JSON", memory_json), \
                 patch("openclaw_trader.strategy.STRATEGY_MEMORY_MD", memory_md), \
                 patch("openclaw_trader.strategy.POSITION_JOURNAL_JSONL", position_journal), \
                 patch("openclaw_trader.strategy.STRATEGY_CHANGE_LOG_JSONL", strategy_change_log):
                payload = build_strategy_memory_perps(
                    runtime,
                    FakeSupervisor(),
                    store,
                    market_items=[
                        {
                            "product_id": "BTC-PERP",
                            "price": "110",
                            "position": {
                                "side": "long",
                                "notional_usd": "50",
                                "entry_price": "100",
                                "opened_at": "2026-03-04T17:00:00+00:00",
                            },
                        }
                    ],
                    current_strategy={
                        "version": 2,
                        "updated_at": "2026-03-04T16:30:00+00:00",
                        "market_regime": "neutral_consolidation",
                        "risk_mode": "defensive",
                        "symbols": [
                            {
                                "symbol": "BTC-PERP",
                                "bias": "neutral",
                                "max_position_share_pct": 0,
                                "max_order_share_pct": 0,
                                "thesis": "wait",
                            }
                        ],
                    },
                    now=datetime(2026, 3, 5, 0, 0, tzinfo=UTC),
                )
            self.assertTrue(memory_json.exists())
            self.assertTrue(memory_md.exists())
            self.assertEqual(payload["recent_orders"]["count"], 1)
            self.assertEqual(payload["current_position_origins"][0]["strategy_version_at_open"], 2)
            self.assertEqual(payload["current_position_origins"][0]["alignment_with_current_strategy"], "legacy")
            self.assertEqual(payload["recent_strategy_changes"][-1]["to_version"], 2)
            self.assertEqual(payload["recent_position_journal"][0]["product_id"], "BTC-PERP")
            self.assertEqual(payload["recent_strategy_change_log"][0]["to_version"], 2)
            self.assertTrue(payload["price_curves"][0]["curves"]["short_term"])
            self.assertIn("当前仓位来历", memory_md.read_text(encoding="utf-8"))
            self.assertIn("原始金额 5 USD | 杠杆 2x", memory_md.read_text(encoding="utf-8"))
            self.assertIn("止损价 98 | 止盈价 114 | 退出计划 跌回区间下沿就继续减仓", memory_md.read_text(encoding="utf-8"))

    def test_build_strategy_memory_perps_includes_reset_baseline_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            history_path = Path(tmpdir) / "strategy-history.jsonl"
            history_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "updated_at": "2026-03-05T01:00:00+00:00",
                        "change_reason": "manual_refresh_reset",
                        "market_regime": "neutral_consolidation",
                        "risk_mode": "defensive",
                        "summary": "fresh start",
                        "invalidators": [],
                        "symbols": [
                            {
                                "symbol": "BTC-PERP",
                                "bias": "neutral",
                                "max_position_share_pct": 0,
                                "max_order_share_pct": 0,
                                "thesis": "wait",
                            }
                        ],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            runtime = RuntimeConfig(
                app=AppConfig(),
                risk=RiskConfig(),
                news=NewsConfig(),
                perps=PerpConfig(exchange="coinbase_intx", coins=["BTC"]),
                dispatch=DispatchConfig(),
                strategy=StrategyConfig(),
                workflow=WorkflowConfig(),
            )
            memory_json = Path(tmpdir) / "strategy-memory.json"
            memory_md = Path(tmpdir) / "strategy-memory.md"
            position_journal = Path(tmpdir) / "position-journal.jsonl"
            strategy_change_log = Path(tmpdir) / "strategy-change-log.jsonl"
            strategy_change_log.write_text(
                json.dumps(
                    {
                        "journaled_at": "2026-03-05T01:00:00+00:00",
                        "from_version": None,
                        "to_version": 1,
                        "change_reason": "manual_refresh_reset",
                        "market_regime_from": None,
                        "market_regime_to": "neutral_consolidation",
                        "risk_mode_from": None,
                        "risk_mode_to": "defensive",
                        "summary_to": "fresh start",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch("openclaw_trader.strategy.STRATEGY_HISTORY_JSONL", history_path), \
                 patch("openclaw_trader.strategy.STRATEGY_MEMORY_JSON", memory_json), \
                 patch("openclaw_trader.strategy.STRATEGY_MEMORY_MD", memory_md), \
                 patch("openclaw_trader.strategy.POSITION_JOURNAL_JSONL", position_journal), \
                 patch("openclaw_trader.strategy.STRATEGY_CHANGE_LOG_JSONL", strategy_change_log):
                payload = build_strategy_memory_perps(
                    runtime,
                    FakeSupervisor(),
                    StateStore(Path(tmpdir) / "trader.db"),
                    market_items=[
                        {
                            "product_id": "BTC-PERP",
                            "price": "110",
                            "position": None,
                        }
                    ],
                    current_strategy={
                        "version": 1,
                        "updated_at": "2026-03-05T01:00:00+00:00",
                        "market_regime": "neutral_consolidation",
                        "risk_mode": "defensive",
                        "symbols": [
                            {
                                "symbol": "BTC-PERP",
                                "bias": "neutral",
                                "max_position_share_pct": 0,
                                "max_order_share_pct": 0,
                                "thesis": "wait",
                            }
                        ],
                    },
                    now=datetime(2026, 3, 5, 2, 0, tzinfo=UTC),
                )
            self.assertEqual(payload["recent_strategy_changes"][0]["from_version"], None)
            self.assertEqual(payload["recent_strategy_changes"][0]["to_version"], 1)


if __name__ == "__main__":
    unittest.main()
