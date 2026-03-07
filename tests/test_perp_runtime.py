from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import openclaw_trader.perps.runtime as runtime_module
from openclaw_trader.config import AppConfig, DispatchConfig, NewsConfig, PerpConfig, RiskConfig, RuntimeConfig, StrategyConfig, WorkflowConfig
from openclaw_trader.models import Candle, NewsItem, PerpSnapshot
from openclaw_trader.models import AutopilotDecision, AutopilotPhase, EmergencyExitDecision, EntryWorkflowMode, PositionRiskStage, RiskEvaluation, RiskProfile, SignalDecision, SignalSide
from openclaw_trader.perps.hyperliquid import HyperliquidPaperContext, HyperliquidPaperEngine
from openclaw_trader.perps.runtime import PerpSupervisor
from openclaw_trader.state import StateStore
from openclaw_trader.strategy import save_strategy_doc


class _FakeClient:
    def __init__(self) -> None:
        self.prices = {"BTC": Decimal("90000"), "ETH": Decimal("3000")}

    def snapshot(self, coin: str = "BTC") -> PerpSnapshot:
        price = self.prices[coin]
        return PerpSnapshot(
            exchange="hyperliquid",
            coin=coin,
            mark_price=price,
            oracle_price=price,
            mid_price=price,
            funding_rate=Decimal("0.0001"),
            premium=Decimal("0"),
            open_interest=Decimal("1000000"),
            max_leverage=Decimal("40"),
            day_notional_volume=Decimal("100000000"),
            raw={},
        )

    def candles(self, coin: str = "BTC", interval: str = "15m", lookback: int = 48):
        base = self.prices[coin]
        closes = [base - Decimal("100") + Decimal(i * 5) for i in range(48)]
        return [
            Candle(start=i, open=c, high=c + 1, low=c - 1, close=c, volume=Decimal("1000"))
            for i, c in enumerate(closes)
        ]


class PerpSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "state.db"
        self.store = StateStore(self.db_path)
        self.runtime = RuntimeConfig(
            app=AppConfig(),
            risk=RiskConfig(),
            news=NewsConfig(),
            perps=PerpConfig(exchange="coinbase_intx", mode="paper", coin="BTC", coins=["BTC", "ETH"], paper_starting_equity_usd=200.0),
            dispatch=DispatchConfig(market_mode="perps"),
            strategy=StrategyConfig(track_products=["BTC", "ETH"]),
            workflow=WorkflowConfig(entry_mode="auto"),
        )
        self.client = _FakeClient()
        self.engine = HyperliquidPaperEngine(HyperliquidPaperContext(config=self.runtime.perps, client=self.client, state=self.store))
        self.supervisor = PerpSupervisor(runtime=self.runtime, state=self.store, engine=self.engine)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_runtime_module_exports_expected_public_api(self) -> None:
        expected_names = [
            "PerpSupervisor",
            "PerpSystemState",
            "load_current_strategy",
        ]
        for name in expected_names:
            self.assertTrue(hasattr(runtime_module, name), name)

    def test_strategy_bias_blocks_coin(self) -> None:
        with tempfile.TemporaryDirectory() as report_dir:
            with patch("openclaw_trader.strategy.REPORT_DIR", Path(report_dir)), patch("openclaw_trader.strategy.STRATEGY_DAY_JSON", Path(report_dir) / "strategy-day.json"), patch("openclaw_trader.strategy.STRATEGY_DAY_MD", Path(report_dir) / "strategy-day.md"), patch("openclaw_trader.strategy.STRATEGY_HISTORY_JSONL", Path(report_dir) / "history.jsonl"), patch("openclaw_trader.strategy.STRATEGY_CHANGE_LOG_JSONL", Path(report_dir) / "strategy-change-log.jsonl"):
                save_strategy_doc(
                    {
                        "strategy_date": "2026-03-03",
                        "updated_at": datetime.now(UTC).isoformat(),
                        "change_reason": "test",
                        "market_regime": "trend",
                        "risk_mode": "normal",
                        "summary": "test",
                        "invalidators": [],
                        "symbols": [
                            {"symbol": "BTC", "bias": "avoid", "max_position_share_pct": 100, "max_order_share_pct": 100, "thesis": "avoid btc"},
                            {"symbol": "ETH", "bias": "long", "max_position_share_pct": 100, "max_order_share_pct": 100, "thesis": "long eth"},
                        ],
                    },
                    datetime.now(UTC),
                )
                from openclaw_trader.perps import runtime as runtime_module
                with patch.object(runtime_module, "load_current_strategy", return_value=json.loads((Path(report_dir) / "strategy-day.json").read_text())):
                    signal, risk = self.supervisor.evaluate_signal("BTC")
                    self.assertEqual(signal.side.value, "flat")
                    self.assertFalse(risk.approved)

    def test_system_state_returns_both_coins(self) -> None:
        state = self.supervisor.system_state()
        self.assertEqual(len(state.decisions), 2)
        self.assertIn(state.primary.product_id, {"BTC-PERP", "ETH-PERP"})

    def test_coinbase_exchange_status_is_relevant_for_coinbase_intx(self) -> None:
        now = datetime.now(UTC)
        item = NewsItem(
            source="coinbase-status",
            title="Degraded Performance - Coinbase Onramp via Apple Pay",
            url="https://status.coinbase.com/incidents/example",
            published_at=now,
            summary="Latency on Apple Pay onramp.",
            tags=["exchange-status"],
            severity="medium",
            layer="exchange-status",
        )
        self.assertTrue(self.supervisor._is_market_relevant_news(item))

    def test_strategy_symbol_limits_override_runtime_defaults(self) -> None:
        with patch.object(
            self.supervisor,
            "_strategy_symbol",
            return_value={"symbol": "BTC-PERP", "max_position_share_pct": 12.0, "max_order_share_pct": 5.0, "bias": "short"},
        ), patch("openclaw_trader.perps.runtime.load_current_strategy", return_value={}):
            max_position, max_order, bias = self.supervisor._symbol_limits("BTC", Decimal("200"))
        self.assertEqual(max_position, Decimal("120.0"))
        self.assertEqual(max_order, Decimal("660.0"))
        self.assertEqual(bias, "short")

    def test_coinbase_official_source_remains_relevant(self) -> None:
        now = datetime.now(UTC)
        item = NewsItem(
            source="x-coinbase-intx",
            title="Coinbase International Exchange posts perpetual market structure update",
            url="https://example.com/coinbase/intx/status/1",
            published_at=now,
            summary="New operational update.",
            tags=["official-x"],
            severity="medium",
            layer="official-x",
        )
        with patch.object(self.supervisor, "recent_news", return_value=[item]):
            decision = self.supervisor.autopilot_check("BTC")
        self.assertEqual(decision.reason, "fresh_relevant_news_requires_observation")

    def test_far_future_event_calendar_does_not_trigger_fresh_news(self) -> None:
        now = datetime.now(UTC) + timedelta(days=7)
        item = NewsItem(
            source="fed-fomc-calendar",
            title="FOMC next week",
            url="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            published_at=now,
            summary="Upcoming meeting window.",
            tags=["event-calendar", "macro"],
            severity="medium",
            layer="event-calendar",
        )
        with patch.object(self.supervisor, "recent_news", return_value=[item]):
            decision = self.supervisor.autopilot_check("BTC")
        self.assertNotEqual(decision.reason, "fresh_relevant_news_requires_observation")

    def test_runtime_ignores_soft_exposure_caps_but_keeps_soft_leverage(self) -> None:
        with tempfile.TemporaryDirectory() as report_dir:
            with patch("openclaw_trader.strategy.REPORT_DIR", Path(report_dir)), \
                 patch("openclaw_trader.strategy.STRATEGY_DAY_JSON", Path(report_dir) / "strategy-day.json"), \
                 patch("openclaw_trader.strategy.STRATEGY_DAY_MD", Path(report_dir) / "strategy-day.md"), \
                 patch("openclaw_trader.strategy.STRATEGY_HISTORY_JSONL", Path(report_dir) / "history.jsonl"), \
                 patch("openclaw_trader.strategy.STRATEGY_CHANGE_LOG_JSONL", Path(report_dir) / "strategy-change-log.jsonl"):
                save_strategy_doc(
                    {
                        "strategy_date": "2026-03-03",
                        "updated_at": datetime.now(UTC).isoformat(),
                        "change_reason": "test",
                        "market_regime": "trend",
                        "risk_mode": "normal",
                        "soft_max_leverage": 3,
                        "summary": "test",
                        "invalidators": [],
                        "symbols": [
                            {"symbol": "BTC-PERP", "bias": "short", "max_position_share_pct": 50, "max_order_share_pct": 25, "thesis": "test"},
                            {"symbol": "ETH-PERP", "bias": "neutral", "max_position_share_pct": 50, "max_order_share_pct": 25, "thesis": "test"},
                        ],
                    },
                    datetime.now(UTC),
                )
                strategy_payload = json.loads((Path(report_dir) / "strategy-day.json").read_text())
                from openclaw_trader.perps import runtime as runtime_module

                with patch.object(runtime_module, "load_current_strategy", return_value=strategy_payload):
                    budget = self.supervisor._exposure_budget_usd(Decimal("200"))
                    min_leverage = self.supervisor._effective_min_leverage()
                    leverage = self.supervisor._effective_max_leverage()
                    max_position, max_order, _ = self.supervisor._symbol_limits("BTC", Decimal("200"))
                self.assertEqual(budget, Decimal("200.0"))
                self.assertEqual(min_leverage, Decimal("1.0"))
                self.assertEqual(leverage, Decimal("3.0"))
                self.assertEqual(max_position, Decimal("300.0"))
                self.assertEqual(max_order, Decimal("396.0"))

    def test_runtime_clamps_soft_leverage_bounds_to_hard_floor(self) -> None:
        with tempfile.TemporaryDirectory() as report_dir:
            with patch("openclaw_trader.strategy.REPORT_DIR", Path(report_dir)), \
                 patch("openclaw_trader.strategy.STRATEGY_DAY_JSON", Path(report_dir) / "strategy-day.json"), \
                 patch("openclaw_trader.strategy.STRATEGY_DAY_MD", Path(report_dir) / "strategy-day.md"), \
                 patch("openclaw_trader.strategy.STRATEGY_HISTORY_JSONL", Path(report_dir) / "history.jsonl"), \
                 patch("openclaw_trader.strategy.STRATEGY_CHANGE_LOG_JSONL", Path(report_dir) / "strategy-change-log.jsonl"):
                save_strategy_doc(
                    {
                        "strategy_date": "2026-03-03",
                        "updated_at": datetime.now(UTC).isoformat(),
                        "change_reason": "test",
                        "market_regime": "trend",
                        "risk_mode": "normal",
                        "soft_min_leverage": 0.5,
                        "soft_max_leverage": 0.8,
                        "summary": "test",
                        "invalidators": [],
                        "symbols": [
                            {"symbol": "BTC-PERP", "bias": "short", "max_position_share_pct": 50, "max_order_share_pct": 25, "thesis": "test"},
                        ],
                    },
                    datetime.now(UTC),
                )
                strategy_payload = json.loads((Path(report_dir) / "strategy-day.json").read_text())
                from openclaw_trader.perps import runtime as runtime_module

                with patch.object(runtime_module, "load_current_strategy", return_value=strategy_payload):
                    min_leverage = self.supervisor._effective_min_leverage()
                    max_leverage = self.supervisor._effective_max_leverage()
                self.assertEqual(min_leverage, Decimal("1.0"))
                self.assertEqual(max_leverage, Decimal("1.0"))

    def test_flip_candidate_uses_post_close_capacity(self) -> None:
        position = self.engine.open_paper(side="short", notional_usd=Decimal("40"), leverage=Decimal("1"), coin="BTC")
        self.assertTrue(position.success)
        mocked_signal = SignalDecision(
            product_id="BTC-PERP",
            side=SignalSide.long,
            confidence=0.82,
            reason="model reversal",
            quote_size_usd=Decimal("12"),
            leverage=Decimal("1"),
            risk_profile=RiskProfile.normal,
        )
        with patch.object(self.supervisor, "_symbol_limits", return_value=(Decimal("40"), Decimal("20"), "neutral")), \
             patch.object(self.supervisor, "_effective_max_leverage", return_value=Decimal("1")), \
             patch.object(self.supervisor.model_service, "predict", return_value=type("Prediction", (), {"signal": mocked_signal, "regime": {"label": "bullish_trend", "confidence": 0.8}})()), \
             patch.object(self.supervisor, "position_drawdown_state", return_value={"drawdown_pct": 0.0, "stage": PositionRiskStage.normal}):
            signal, risk = self.supervisor.evaluate_signal("BTC")
        self.assertEqual(signal.side, SignalSide.long)
        self.assertTrue(risk.approved)
        self.assertEqual(risk.max_allowed_quote_usd, Decimal("20"))

    def test_tiered_signal_leverage_respects_confidence_bands(self) -> None:
        with patch.object(self.supervisor, "_effective_min_leverage", return_value=Decimal("1")), \
             patch.object(self.supervisor, "_effective_max_leverage", return_value=Decimal("5")):
            weak = self.supervisor._tiered_signal_leverage(
                SignalDecision(
                    product_id="BTC-PERP",
                    side=SignalSide.long,
                    confidence=0.65,
                    reason="weak",
                    quote_size_usd=Decimal("10"),
                    leverage=Decimal("1"),
                    risk_profile=RiskProfile.normal,
                )
            )
            medium = self.supervisor._tiered_signal_leverage(
                SignalDecision(
                    product_id="BTC-PERP",
                    side=SignalSide.long,
                    confidence=0.75,
                    reason="medium",
                    quote_size_usd=Decimal("10"),
                    leverage=Decimal("1"),
                    risk_profile=RiskProfile.normal,
                )
            )
            strong = self.supervisor._tiered_signal_leverage(
                SignalDecision(
                    product_id="BTC-PERP",
                    side=SignalSide.long,
                    confidence=0.90,
                    reason="strong",
                    quote_size_usd=Decimal("10"),
                    leverage=Decimal("1"),
                    risk_profile=RiskProfile.normal,
                )
            )
            flat = self.supervisor._tiered_signal_leverage(
                SignalDecision(
                    product_id="BTC-PERP",
                    side=SignalSide.flat,
                    confidence=0.90,
                    reason="flat",
                    quote_size_usd=Decimal("0"),
                    leverage=Decimal("1"),
                    risk_profile=RiskProfile.normal,
                )
            )
        self.assertEqual(weak, Decimal("2.0"))
        self.assertEqual(medium, Decimal("3.0"))
        self.assertEqual(strong, Decimal("5.0"))
        self.assertEqual(flat, Decimal("1"))

    def test_neutral_zero_strategy_allows_strong_signal_override_with_1x_cap(self) -> None:
        self.runtime.strategy.enable_neutral_signal_override = True
        mocked_signal = SignalDecision(
            product_id="BTC-PERP",
            side=SignalSide.short,
            confidence=0.90,
            reason="strong short",
            quote_size_usd=Decimal("12"),
            leverage=Decimal("5"),
            risk_profile=RiskProfile.normal,
        )
        with patch.object(
            self.supervisor,
            "_strategy_symbol",
            return_value={"symbol": "BTC-PERP", "bias": "neutral", "max_position_share_pct": 0, "max_order_share_pct": 0},
        ), patch.object(
            self.supervisor.model_service,
            "predict",
            return_value=type("Prediction", (), {"signal": mocked_signal, "regime": {"label": "neutral_consolidation", "confidence": 0.8}})(),
        ), patch.object(
            self.supervisor,
            "position_drawdown_state",
            return_value={"drawdown_pct": 0.0, "stage": PositionRiskStage.normal},
        ):
            signal, risk = self.supervisor.evaluate_signal("BTC")
        self.assertEqual(signal.leverage, Decimal("1"))
        self.assertEqual(signal.quote_size_usd, Decimal("12.00000000"))
        self.assertTrue(signal.metadata["neutral_signal_override_active"])
        self.assertEqual(signal.metadata["neutral_signal_override_tier"], "strong")
        self.assertTrue(risk.approved)
        self.assertEqual(risk.max_allowed_quote_usd, Decimal("40.0"))

    def test_neutral_zero_strategy_allows_medium_signal_override_with_1x_and_10pct_cap(self) -> None:
        self.runtime.strategy.enable_neutral_signal_override = True
        mocked_signal = SignalDecision(
            product_id="BTC-PERP",
            side=SignalSide.short,
            confidence=0.75,
            reason="medium short",
            quote_size_usd=Decimal("12"),
            leverage=Decimal("5"),
            risk_profile=RiskProfile.normal,
        )
        with patch.object(
            self.supervisor,
            "_strategy_symbol",
            return_value={"symbol": "BTC-PERP", "bias": "neutral", "max_position_share_pct": 0, "max_order_share_pct": 0},
        ), patch.object(
            self.supervisor.model_service,
            "predict",
            return_value=type("Prediction", (), {"signal": mocked_signal, "regime": {"label": "neutral_consolidation", "confidence": 0.8}})(),
        ), patch.object(
            self.supervisor,
            "position_drawdown_state",
            return_value={"drawdown_pct": 0.0, "stage": PositionRiskStage.normal},
        ):
            signal, risk = self.supervisor.evaluate_signal("BTC")
        self.assertEqual(signal.leverage, Decimal("1"))
        self.assertEqual(signal.quote_size_usd, Decimal("12.00000000"))
        self.assertTrue(signal.metadata["neutral_signal_override_active"])
        self.assertEqual(signal.metadata["neutral_signal_override_tier"], "medium")
        self.assertTrue(risk.approved)
        self.assertEqual(risk.max_allowed_quote_usd, Decimal("20.0"))

    def test_close_plan_uses_current_position_leverage_for_display(self) -> None:
        opened = self.engine.open_paper(side="short", notional_usd=Decimal("30"), leverage=Decimal("3"), coin="BTC")
        self.assertTrue(opened.success)
        signal = SignalDecision(
            product_id="BTC-PERP",
            side=SignalSide.flat,
            confidence=0.95,
            reason="flat",
            quote_size_usd=Decimal("0"),
            leverage=Decimal("1"),
            risk_profile=RiskProfile.normal,
        )
        risk = RiskEvaluation(
            approved=False,
            reason="flat_signal",
            max_allowed_quote_usd=Decimal("0"),
        )
        panic = EmergencyExitDecision(should_exit=False, reason="normal", triggers=[])
        with patch.object(
            self.supervisor,
            "_strategy_symbol",
            return_value={"symbol": "BTC-PERP", "bias": "neutral", "max_position_share_pct": 0, "max_order_share_pct": 0},
        ), patch.object(
            self.supervisor,
            "evaluate_signal",
            return_value=(signal, risk),
        ), patch.object(
            self.supervisor,
            "evaluate_emergency_exit",
            return_value=panic,
        ), patch.object(
            self.supervisor,
            "recent_news",
            return_value=[],
        ):
            decision = self.supervisor.autopilot_check("BTC")
        self.assertEqual(decision.phase, AutopilotPhase.trade)
        plan = (decision.preview or {}).get("plan") or {}
        self.assertEqual(plan["action"], "close")
        self.assertEqual(plan["execution_leverage"], "3")
        self.assertEqual(plan["current_position_leverage"], "3")

    def test_neutral_zero_strategy_strong_signal_creates_trade_plan(self) -> None:
        self.runtime.strategy.enable_neutral_signal_override = True
        mocked_signal = SignalDecision(
            product_id="BTC-PERP",
            side=SignalSide.short,
            confidence=0.90,
            reason="strong short",
            quote_size_usd=Decimal("12"),
            leverage=Decimal("5"),
            risk_profile=RiskProfile.normal,
        )
        with patch.object(
            self.supervisor,
            "_strategy_symbol",
            return_value={"symbol": "BTC-PERP", "bias": "neutral", "max_position_share_pct": 0, "max_order_share_pct": 0},
        ), patch.object(
            self.supervisor.model_service,
            "predict",
            return_value=type("Prediction", (), {"signal": mocked_signal, "regime": {"label": "neutral_consolidation", "confidence": 0.8}})(),
        ), patch.object(
            self.supervisor,
            "position_drawdown_state",
            return_value={"drawdown_pct": 0.0, "stage": PositionRiskStage.normal},
        ), patch.object(
            self.supervisor,
            "recent_news",
            return_value=[],
        ):
            decision = self.supervisor.autopilot_check("BTC")
        self.assertEqual(decision.phase, AutopilotPhase.trade)
        self.assertEqual(decision.reason, "paper_trade_candidate_ready")
        self.assertEqual(decision.signal.metadata["strategy_target_side"], "short")
        self.assertEqual(Decimal(decision.preview["plan"]["notional_usd"]), Decimal("40.0"))
        self.assertEqual(Decimal(decision.preview["plan"]["execution_leverage"]), Decimal("1"))

    def test_neutral_zero_strategy_keeps_strong_signal_flat_when_override_switch_is_off(self) -> None:
        mocked_signal = SignalDecision(
            product_id="BTC-PERP",
            side=SignalSide.short,
            confidence=0.90,
            reason="strong short",
            quote_size_usd=Decimal("12"),
            leverage=Decimal("5"),
            risk_profile=RiskProfile.normal,
        )
        with patch.object(
            self.supervisor,
            "_strategy_symbol",
            return_value={"symbol": "BTC-PERP", "bias": "neutral", "max_position_share_pct": 0, "max_order_share_pct": 0},
        ), patch.object(
            self.supervisor.model_service,
            "predict",
            return_value=type("Prediction", (), {"signal": mocked_signal, "regime": {"label": "neutral_consolidation", "confidence": 0.8}})(),
        ), patch.object(
            self.supervisor,
            "position_drawdown_state",
            return_value={"drawdown_pct": 0.0, "stage": PositionRiskStage.normal},
        ), patch.object(
            self.supervisor,
            "recent_news",
            return_value=[],
        ):
            signal, risk = self.supervisor.evaluate_signal("BTC")
            decision = self.supervisor.autopilot_check("BTC")
        self.assertFalse(signal.metadata["neutral_signal_override_active"])
        self.assertIsNone(signal.metadata.get("neutral_signal_override_tier"))
        self.assertEqual(signal.leverage, Decimal("5.0"))
        self.assertFalse(risk.approved)
        self.assertEqual(risk.reason, "signal_quote_above_limit")
        self.assertEqual(decision.phase, AutopilotPhase.heartbeat)
        self.assertEqual(decision.signal.metadata["strategy_plan_reason"], "strategy_target_is_flat")

    def test_system_state_rotates_primary_across_same_phase(self) -> None:
        btc = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=True,
            reason="paper_trade_candidate_ready",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(
                product_id="BTC-PERP",
                side=SignalSide.long,
                confidence=0.8,
                reason="test",
                risk_profile=RiskProfile.normal,
            ),
            risk=RiskEvaluation(approved=True, reason="approved", max_allowed_quote_usd="10"),
        )
        eth = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=True,
            reason="paper_trade_candidate_ready",
            product_id="ETH-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(
                product_id="ETH-PERP",
                side=SignalSide.long,
                confidence=0.7,
                reason="test",
                risk_profile=RiskProfile.normal,
            ),
            risk=RiskEvaluation(approved=True, reason="approved", max_allowed_quote_usd="10"),
        )
        with patch.object(self.supervisor, "autopilot_check", side_effect=[btc, eth, btc, eth]):
            first = self.supervisor.system_state()
            second = self.supervisor.system_state()
        self.assertEqual(first.primary.product_id, "BTC-PERP")
        self.assertEqual(second.primary.product_id, "ETH-PERP")

    def test_autopilot_check_reduces_existing_position_toward_strategy_target(self) -> None:
        opened = self.engine.open_paper(side="long", notional_usd=Decimal("40"), leverage=Decimal("1"), coin="BTC")
        self.assertTrue(opened.success)
        mocked_signal = SignalDecision(
            product_id="BTC-PERP",
            side=SignalSide.flat,
            confidence=0.75,
            reason="strategy should rebalance",
            quote_size_usd=Decimal("0"),
            leverage=Decimal("1"),
            risk_profile=RiskProfile.normal,
        )
        mocked_risk = RiskEvaluation(approved=False, reason="flat_signal", max_allowed_quote_usd=Decimal("0"))
        mocked_panic = EmergencyExitDecision(
            should_exit=False,
            reason="no_hard_exit_trigger",
            position_drawdown_pct=0.0,
            position_risk_stage=PositionRiskStage.normal,
        )
        with patch.object(self.supervisor, "evaluate_signal", return_value=(mocked_signal, mocked_risk)), \
             patch.object(self.supervisor, "evaluate_emergency_exit", return_value=mocked_panic), \
             patch.object(self.supervisor, "recent_news", return_value=[]), \
             patch.object(self.supervisor, "_symbol_limits", return_value=(Decimal("10"), Decimal("5"), "long")):
            decision = self.supervisor.autopilot_check("BTC")
        self.assertEqual(decision.phase, AutopilotPhase.trade)
        self.assertEqual(decision.preview["plan"]["action"], "reduce")
        self.assertEqual(Decimal(decision.preview["plan"]["notional_usd"]), Decimal("30"))

    def test_autopilot_check_skips_entry_below_exchange_min_notional(self) -> None:
        mocked_signal = SignalDecision(
            product_id="BTC-PERP",
            side=SignalSide.long,
            confidence=0.72,
            reason="target too small",
            quote_size_usd=Decimal("3"),
            leverage=Decimal("1"),
            risk_profile=RiskProfile.normal,
        )
        mocked_risk = RiskEvaluation(approved=True, reason="approved", max_allowed_quote_usd=Decimal("3"))
        mocked_panic = EmergencyExitDecision(
            should_exit=False,
            reason="no_hard_exit_trigger",
            position_drawdown_pct=0.0,
            position_risk_stage=PositionRiskStage.normal,
        )
        with patch.object(self.supervisor, "evaluate_signal", return_value=(mocked_signal, mocked_risk)), \
             patch.object(self.supervisor, "evaluate_emergency_exit", return_value=mocked_panic), \
             patch.object(self.supervisor, "recent_news", return_value=[]), \
             patch.object(self.supervisor, "_symbol_limits", return_value=(Decimal("8"), Decimal("8"), "long")), \
             patch.object(self.supervisor.engine, "minimum_trade_notional_usd", return_value=Decimal("10")):
            decision = self.supervisor.autopilot_check("BTC")
        self.assertNotEqual(decision.phase, AutopilotPhase.trade)
        self.assertEqual(decision.signal.metadata["strategy_plan_reason"], "below_exchange_min_notional")

    def test_autopilot_check_keeps_neutral_bias_flat_for_substrong_signal(self) -> None:
        mocked_signal = SignalDecision(
            product_id="BTC-PERP",
            side=SignalSide.short,
            confidence=0.69,
            reason="directional model signal",
            quote_size_usd=Decimal("12"),
            leverage=Decimal("1"),
            risk_profile=RiskProfile.normal,
        )
        mocked_risk = RiskEvaluation(approved=True, reason="approved", max_allowed_quote_usd=Decimal("12"))
        mocked_panic = EmergencyExitDecision(
            should_exit=False,
            reason="no_hard_exit_trigger",
            position_drawdown_pct=0.0,
            position_risk_stage=PositionRiskStage.normal,
        )
        with patch.object(self.supervisor, "evaluate_signal", return_value=(mocked_signal, mocked_risk)), \
             patch.object(self.supervisor, "evaluate_emergency_exit", return_value=mocked_panic), \
             patch.object(self.supervisor, "recent_news", return_value=[]), \
             patch.object(self.supervisor, "_strategy_symbol", return_value={"symbol": "BTC-PERP", "bias": "neutral", "max_position_share_pct": 0, "max_order_share_pct": 0}), \
             patch.object(self.supervisor, "_symbol_limits", return_value=(Decimal("20"), Decimal("10"), "neutral")):
            decision = self.supervisor.autopilot_check("BTC")
        self.assertEqual(decision.phase, AutopilotPhase.heartbeat)
        self.assertEqual(decision.signal.metadata["strategy_target_side"], None)
        self.assertEqual(decision.signal.metadata["strategy_target_quote_usd"], "0")
        self.assertEqual(decision.signal.metadata["strategy_plan_reason"], "strategy_target_is_flat")

    def test_apply_trade_plan_handles_add_and_reduce(self) -> None:
        opened = self.engine.open_paper(side="long", notional_usd=Decimal("20"), leverage=Decimal("1"), coin="BTC")
        self.assertTrue(opened.success)
        decision = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=False,
            reason="paper_trade_candidate_ready",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(
                product_id="BTC-PERP",
                side=SignalSide.long,
                confidence=0.8,
                reason="rebalance",
                risk_profile=RiskProfile.normal,
            ),
        )

        add_result = self.supervisor.apply_trade_plan(
            decision,
            plan_override={"action": "add", "side": "long", "notional_usd": "5", "coin": "BTC"},
        )
        self.assertEqual(add_result["results"][0]["action"], "add")
        self.assertEqual(self.engine.position("BTC").notional_usd, Decimal("25"))

        reduce_result = self.supervisor.apply_trade_plan(
            decision,
            plan_override={"action": "reduce", "side": "long", "notional_usd": "7", "coin": "BTC"},
        )
        self.assertEqual(reduce_result["results"][0]["action"], "reduce")
        self.assertEqual(self.engine.position("BTC").notional_usd, Decimal("18"))

    def test_apply_trade_plan_clamps_execution_leverage_to_strategy_soft_floor(self) -> None:
        decision = AutopilotDecision(
            phase=AutopilotPhase.trade,
            notify_user=False,
            reason="paper_trade_candidate_ready",
            product_id="BTC-PERP",
            flow_mode=EntryWorkflowMode.auto,
            signal=SignalDecision(
                product_id="BTC-PERP",
                side=SignalSide.long,
                confidence=0.8,
                reason="rebalance",
                leverage=Decimal("1"),
                risk_profile=RiskProfile.normal,
            ),
            preview={"plan": {"action": "open", "side": "long", "notional_usd": "20", "coin": "BTC"}},
        )
        from openclaw_trader.perps import runtime as runtime_module

        with patch.object(
            runtime_module,
            "load_current_strategy",
            return_value={"soft_min_leverage": 2.0, "soft_max_leverage": 3.0},
        ):
            result = self.supervisor.apply_trade_plan(decision)
        self.assertIsNotNone(result)
        position = self.engine.position("BTC")
        self.assertIsNotNone(position)
        assert position is not None
        self.assertEqual(position.leverage, Decimal("2.0"))

    def test_position_drawdown_state_resets_after_side_change_without_intermediate_poll(self) -> None:
        opened = self.engine.open_paper(side="long", notional_usd=Decimal("40"), leverage=Decimal("1"), coin="BTC")
        self.assertTrue(opened.success)
        initial = self.supervisor.position_drawdown_state("BTC")
        self.assertEqual(initial["drawdown_pct"], 0.0)
        self.assertEqual(initial["peak_value_usd"], Decimal("40"))

        closed = self.engine.close_paper("BTC")
        self.assertTrue(closed.success)
        reopened = self.engine.open_paper(side="short", notional_usd=Decimal("10"), leverage=Decimal("1"), coin="BTC")
        self.assertTrue(reopened.success)

        reset = self.supervisor.position_drawdown_state("BTC")
        self.assertEqual(reset["drawdown_pct"], 0.0)
        self.assertEqual(reset["peak_value_usd"], Decimal("10"))
        self.assertEqual(reset["position_identity"]["side"], "short")

    def test_panic_coin_cooldown_blocks_same_coin_only_and_auto_expires(self) -> None:
        now = datetime.now(UTC)
        mocked_risk = RiskEvaluation(approved=True, reason="approved", max_allowed_quote_usd=Decimal("10"))
        mocked_panic = EmergencyExitDecision(
            should_exit=False,
            reason="no_hard_exit_trigger",
            position_drawdown_pct=0.0,
            position_risk_stage=PositionRiskStage.normal,
        )

        self.supervisor.register_panic_exit(
            now=now,
            coin="ETH",
            trigger_reason="risk_layer_approved_emergency_exit",
            trigger_product_id="ETH-PERP",
            trigger_triggers=["position_drawdown_exit"],
        )

        eth_signal = SignalDecision(
            product_id="ETH-PERP",
            side=SignalSide.short,
            confidence=0.82,
            reason="short signal",
            quote_size_usd=Decimal("10"),
            leverage=Decimal("1"),
            risk_profile=RiskProfile.normal,
        )
        btc_signal = SignalDecision(
            product_id="BTC-PERP",
            side=SignalSide.short,
            confidence=0.82,
            reason="short signal",
            quote_size_usd=Decimal("10"),
            leverage=Decimal("1"),
            risk_profile=RiskProfile.normal,
        )

        with patch.object(self.supervisor, "evaluate_signal", return_value=(eth_signal, mocked_risk)), \
             patch.object(self.supervisor, "evaluate_emergency_exit", return_value=mocked_panic), \
             patch.object(self.supervisor, "recent_news", return_value=[]), \
             patch.object(self.supervisor, "_symbol_limits", return_value=(Decimal("20"), Decimal("10"), "short")):
            eth_locked = self.supervisor.autopilot_check("ETH")
        self.assertNotEqual(eth_locked.phase, AutopilotPhase.trade)
        self.assertEqual(eth_locked.signal.metadata["strategy_plan_reason"], "panic_coin_cooldown_active")
        self.assertTrue(eth_locked.signal.metadata["panic_coin_cooldown_active"])
        self.assertFalse(eth_locked.signal.metadata["panic_global_breaker_active"])

        with patch.object(self.supervisor, "evaluate_signal", return_value=(btc_signal, mocked_risk)), \
             patch.object(self.supervisor, "evaluate_emergency_exit", return_value=mocked_panic), \
             patch.object(self.supervisor, "recent_news", return_value=[]), \
             patch.object(self.supervisor, "_symbol_limits", return_value=(Decimal("20"), Decimal("10"), "short")):
            btc_trade = self.supervisor.autopilot_check("BTC")
        self.assertEqual(btc_trade.phase, AutopilotPhase.trade)
        self.assertEqual(btc_trade.preview["plan"]["action"], "open")

        future_status = self.supervisor.panic_protection_status(now=now + timedelta(minutes=31))
        self.assertFalse(future_status["active"])
        self.assertEqual(future_status["coin_cooldowns"], [])

    def test_two_recent_panic_exits_trigger_global_breaker(self) -> None:
        now = datetime.now(UTC)
        first = self.supervisor.register_panic_exit(
            now=now,
            coin="ETH",
            trigger_reason="risk_layer_approved_emergency_exit",
            trigger_product_id="ETH-PERP",
            trigger_triggers=["position_drawdown_exit"],
        )
        self.assertFalse(first["global_breaker_active"])

        second = self.supervisor.register_panic_exit(
            now=now + timedelta(minutes=20),
            coin="BTC",
            trigger_reason="risk_layer_approved_emergency_exit",
            trigger_product_id="BTC-PERP",
            trigger_triggers=["position_drawdown_exit"],
        )
        self.assertTrue(second["global_breaker_active"])
        breaker = second["global_breaker"]
        self.assertIsNotNone(breaker)
        self.assertEqual(breaker["recent_panic_count"], 2)
        self.assertEqual(
            datetime.fromisoformat(breaker["until"]),
            (now + timedelta(minutes=20) + timedelta(hours=4)).astimezone(UTC),
        )

        mocked_signal = SignalDecision(
            product_id="ETH-PERP",
            side=SignalSide.short,
            confidence=0.82,
            reason="short signal",
            quote_size_usd=Decimal("10"),
            leverage=Decimal("1"),
            risk_profile=RiskProfile.normal,
        )
        mocked_risk = RiskEvaluation(approved=True, reason="approved", max_allowed_quote_usd=Decimal("10"))
        mocked_panic = EmergencyExitDecision(
            should_exit=False,
            reason="no_hard_exit_trigger",
            position_drawdown_pct=0.0,
            position_risk_stage=PositionRiskStage.normal,
        )
        with patch.object(self.supervisor, "panic_protection_status", return_value=second), \
             patch.object(self.supervisor, "evaluate_signal", return_value=(mocked_signal, mocked_risk)), \
             patch.object(self.supervisor, "evaluate_emergency_exit", return_value=mocked_panic), \
             patch.object(self.supervisor, "recent_news", return_value=[]), \
             patch.object(self.supervisor, "_symbol_limits", return_value=(Decimal("20"), Decimal("10"), "short")):
            blocked = self.supervisor.autopilot_check("ETH")
        self.assertNotEqual(blocked.phase, AutopilotPhase.trade)
        self.assertEqual(blocked.signal.metadata["strategy_plan_reason"], "panic_global_breaker_active")
        self.assertTrue(blocked.signal.metadata["panic_global_breaker_active"])

    def test_old_panic_events_outside_window_do_not_trigger_global_breaker(self) -> None:
        now = datetime.now(UTC)
        self.supervisor.register_panic_exit(
            now=now - timedelta(hours=7),
            coin="ETH",
            trigger_reason="risk_layer_approved_emergency_exit",
            trigger_product_id="ETH-PERP",
            trigger_triggers=["position_drawdown_exit"],
        )
        current = self.supervisor.register_panic_exit(
            now=now,
            coin="BTC",
            trigger_reason="risk_layer_approved_emergency_exit",
            trigger_product_id="BTC-PERP",
            trigger_triggers=["position_drawdown_exit"],
        )
        self.assertFalse(current["global_breaker_active"])
        self.assertEqual(len(current["recent_panic_events"]), 1)


if __name__ == "__main__":
    unittest.main()
