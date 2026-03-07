from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from openclaw_trader.config import PerpConfig
from openclaw_trader.models import PerpSnapshot
from openclaw_trader.perps.hyperliquid import HyperliquidPaperContext, HyperliquidPaperEngine, HyperliquidPublicClient
from openclaw_trader.state import StateStore


class _FakeHyperliquidClient:
    def __init__(self, mark_price: str = "70000", funding: str = "0.0001") -> None:
        self.mark_price = Decimal(mark_price)
        self.funding = Decimal(funding)

    def snapshot(self, coin: str = "BTC") -> PerpSnapshot:
        return PerpSnapshot(
            exchange="hyperliquid",
            coin=coin,
            mark_price=self.mark_price,
            oracle_price=self.mark_price,
            mid_price=self.mark_price,
            funding_rate=self.funding,
            premium=Decimal("0"),
            open_interest=Decimal("10000"),
            max_leverage=Decimal("40"),
            day_notional_volume=Decimal("100000000"),
            raw={},
        )


class HyperliquidPaperEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "paper.db"
        self.state = StateStore(self.db_path)
        self.config = PerpConfig(
            exchange="hyperliquid",
            mode="paper",
            coin="BTC",
            coins=["BTC", "ETH"],
            paper_starting_equity_usd=200.0,
            max_order_share_pct_of_exposure_budget=100.0,
            max_position_share_pct_of_exposure_budget=100.0,
            max_total_exposure_pct_of_equity=100.0,
            max_leverage=2.0,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_open_and_close_paper_position(self) -> None:
        client = _FakeHyperliquidClient(mark_price="70000")
        engine = HyperliquidPaperEngine(HyperliquidPaperContext(config=self.config, client=client, state=self.state))

        opened = engine.open_paper(side="long", notional_usd=Decimal("20"), leverage=Decimal("2"))
        self.assertTrue(opened.success)
        account = engine.account()
        self.assertIsNotNone(account.position)
        self.assertEqual(account.position.side, "long")

        client.mark_price = Decimal("71400")
        closed = engine.close_paper()
        self.assertTrue(closed.success)
        self.assertGreater(closed.realized_pnl_usd, Decimal("0"))

        post = engine.account()
        self.assertIsNone(post.position)
        self.assertGreater(post.realized_pnl_usd, Decimal("0"))

    def test_add_and_reduce_paper_position(self) -> None:
        client = _FakeHyperliquidClient(mark_price="70000")
        engine = HyperliquidPaperEngine(HyperliquidPaperContext(config=self.config, client=client, state=self.state))

        opened = engine.open_paper(side="long", notional_usd=Decimal("20"), leverage=Decimal("2"))
        self.assertTrue(opened.success)

        added = engine.add_paper(side="long", notional_usd=Decimal("10"), leverage=Decimal("2"))
        self.assertTrue(added.success)
        account = engine.account()
        self.assertEqual(account.position.notional_usd, Decimal("30"))

        client.mark_price = Decimal("71000")
        reduced = engine.reduce_paper(notional_usd=Decimal("12"))
        self.assertTrue(reduced.success)
        account = engine.account()
        self.assertEqual(account.position.notional_usd, Decimal("18"))
        self.assertGreater(reduced.realized_pnl_usd, Decimal("0"))

    def test_open_rejects_order_above_limit(self) -> None:
        client = _FakeHyperliquidClient(mark_price="70000")
        engine = HyperliquidPaperEngine(HyperliquidPaperContext(config=self.config, client=client, state=self.state))
        rejected = engine.open_paper(side="long", notional_usd=Decimal("250"), leverage=Decimal("2"))
        self.assertFalse(rejected.success)
        self.assertEqual(rejected.message, "notional_above_order_limit")

    def test_shared_equity_and_total_exposure_limit(self) -> None:
        client = _FakeHyperliquidClient(mark_price="70000")
        engine = HyperliquidPaperEngine(HyperliquidPaperContext(config=self.config, client=client, state=self.state))
        opened_btc = engine.open_paper(side="long", notional_usd=Decimal("120"), leverage=Decimal("2"), coin="BTC")
        self.assertTrue(opened_btc.success)
        opened_eth = engine.open_paper(side="long", notional_usd=Decimal("100"), leverage=Decimal("2"), coin="ETH")
        self.assertFalse(opened_eth.success)
        self.assertEqual(opened_eth.message, "total_exposure_above_limit")
        portfolio = engine.portfolio()
        self.assertEqual(len(portfolio.positions), 1)

    def test_public_client_retries_rate_limit_once(self) -> None:
        client = HyperliquidPublicClient("https://api.hyperliquid.xyz")
        responses = [
            HTTPError(url="https://api.hyperliquid.xyz/info", code=429, msg="Too Many Requests", hdrs=None, fp=None),
            [{"name": "BTC"}],  # not used directly, just placeholder for meta below
        ]

        def fake_urlopen(req, timeout=20):
            item = responses.pop(0)
            if isinstance(item, Exception):
                raise item
            class _Resp:
                def __enter__(self_nonlocal):
                    self_nonlocal._payload = json_bytes
                    return self_nonlocal
                def __exit__(self_nonlocal, exc_type, exc, tb):
                    return False
                def read(self_nonlocal):
                    return self_nonlocal._payload
            return _Resp()

        json_bytes = b'[{"ok":true}]'
        with patch("openclaw_trader.perps.hyperliquid.request.urlopen", side_effect=fake_urlopen) as mocked, \
             patch("openclaw_trader.perps.hyperliquid.time.sleep", return_value=None):
            payload = client._post_info({"type": "metaAndAssetCtxs"})
        self.assertEqual(payload, [{"ok": True}])
        self.assertEqual(mocked.call_count, 2)


if __name__ == "__main__":
    unittest.main()
