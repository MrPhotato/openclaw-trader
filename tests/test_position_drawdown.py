from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from openclaw_trader.config import AppConfig, DispatchConfig, NewsConfig, PerpConfig, RiskConfig, RuntimeConfig, StrategyConfig, WorkflowConfig
from openclaw_trader.engine import EngineContext, TraderEngine
from openclaw_trader.models import Balance, PositionRiskStage, ProductSnapshot
from openclaw_trader.state import StateStore


class _FakeClient:
    def __init__(self, price: Decimal):
        self.price = price

    def list_accounts(self):
        return [
            Balance(currency="USDC", available=Decimal("100"), hold=Decimal("0")),
            Balance(currency="BTC", available=Decimal("1"), hold=Decimal("0")),
        ]

    def get_product(self, product_id: str):
        return ProductSnapshot(
            product_id=product_id,
            price=self.price,
            base_increment=Decimal("0.00000001"),
            quote_increment=Decimal("0.01"),
            quote_min_size=Decimal("1"),
        )


class PositionDrawdownTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.tmpdir.name) / "state.db")
        self.runtime = RuntimeConfig(
            app=AppConfig(),
            risk=RiskConfig(
                position_observe_drawdown_pct=4.0,
                position_reduce_drawdown_pct=7.0,
                position_exit_drawdown_pct=10.0,
                emergency_exit_enabled=True,
                emergency_exit_on_exchange_status=False,
            ),
            news=NewsConfig(),
            perps=PerpConfig(),
            strategy=StrategyConfig(),
            workflow=WorkflowConfig(),
            dispatch=DispatchConfig(),
        )

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def _engine(self, price: str) -> TraderEngine:
        return TraderEngine(
            EngineContext(
                runtime=self.runtime,
                client=_FakeClient(Decimal(price)),
                state=self.store,
            )
        )

    def test_position_drawdown_stages_follow_peak_by_product(self) -> None:
        with patch("openclaw_trader.engine.sync_news", return_value=None):
            normal = self._engine("100").evaluate_emergency_exit("BTC-USDC")
            observe = self._engine("95").evaluate_emergency_exit("BTC-USDC")
            reduce = self._engine("92").evaluate_emergency_exit("BTC-USDC")
            exit_decision = self._engine("89").evaluate_emergency_exit("BTC-USDC")

        self.assertEqual(normal.position_risk_stage, PositionRiskStage.normal)
        self.assertEqual(observe.position_risk_stage, PositionRiskStage.observe)
        self.assertEqual(reduce.position_risk_stage, PositionRiskStage.reduce)
        self.assertEqual(exit_decision.position_risk_stage, PositionRiskStage.exit)
        self.assertTrue(exit_decision.should_exit)
        self.assertIn("position_drawdown_exit", exit_decision.triggers)


if __name__ == "__main__":
    unittest.main()
