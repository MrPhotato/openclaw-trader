from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from openclaw_trader.config import AppConfig, DispatchConfig, ModelConfig, NewsConfig, PerpConfig, RiskConfig, RuntimeConfig, StrategyConfig, WorkflowConfig
from openclaw_trader.ml.pipeline import PerpModelService
from openclaw_trader.models import Candle, PerpSnapshot


class _FakePerpEngine:
    def __init__(self) -> None:
        self._prices = {"BTC": Decimal("68000"), "ETH": Decimal("2200")}

    def candles(self, coin: str, interval: str = "15m", lookback: int = 1500):
        base = float(self._prices[coin])
        candles: list[Candle] = []
        for idx in range(lookback):
            drift = 0.6 if coin == "BTC" else -0.3
            wave = ((idx % 48) - 24) * 0.12
            close = Decimal(str(base + (idx * drift) + wave))
            open_ = close - Decimal("4")
            high = close + Decimal("8")
            low = close - Decimal("8")
            volume = Decimal(str(1000 + (idx % 30) * 17))
            candles.append(Candle(start=idx, open=open_, high=high, low=low, close=close, volume=volume))
        return candles

    def snapshot(self, coin: str):
        price = self._prices[coin]
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


class PerpModelServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.runtime = RuntimeConfig(
            app=AppConfig(),
            risk=RiskConfig(),
            news=NewsConfig(),
            perps=PerpConfig(mode="paper", coin="BTC", coins=["BTC", "ETH"], paper_starting_equity_usd=200.0),
            dispatch=DispatchConfig(market_mode="perps"),
            strategy=StrategyConfig(track_products=["BTC", "ETH"]),
            model=ModelConfig(history_bars=600, min_train_samples=200),
            workflow=WorkflowConfig(entry_mode="auto"),
        )
        self.engine = _FakePerpEngine()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_train_and_predict(self) -> None:
        with patch("openclaw_trader.ml.pipeline.MODEL_DIR", Path(self.temp_dir.name)):
            service = PerpModelService(runtime=self.runtime, engine=self.engine)
            meta = service.train_models("BTC")["meta"]
            self.assertEqual(meta["coin"], "BTC")
            prediction = service.predict("BTC", max_order_quote_usd=Decimal("10"), leverage=Decimal("2"))
            self.assertIn(prediction.signal.side.value, {"long", "short", "flat"})
            self.assertIn(prediction.regime["label"], {"bullish_trend", "bearish_breakdown", "neutral_consolidation"})
            self.assertGreaterEqual(prediction.signal.confidence, 0.0)


if __name__ == "__main__":
    unittest.main()
