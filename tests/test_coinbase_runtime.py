from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch

import certifi
import httpx
import ssl

from openclaw_trader.coinbase import CoinbaseAdvancedClient
from openclaw_trader.config import CoinbaseCredentials, PerpConfig, RuntimeConfig, AppConfig, DispatchConfig, NewsConfig, RiskConfig, StrategyConfig, WorkflowConfig
from openclaw_trader.models import Candle, OrderResult, ProductSnapshot
from openclaw_trader.perps import build_perp_engine
from openclaw_trader.perps.coinbase_intx import CoinbaseIntxContext, CoinbaseIntxEngine
from openclaw_trader.state import StateStore


class CoinbaseAdvancedClientTests(unittest.TestCase):
    def test_client_uses_certifi_and_ignores_ambient_ssl_env(self) -> None:
        with patch("openclaw_trader.coinbase.httpx.Client") as client_factory:
            CoinbaseAdvancedClient(
                CoinbaseCredentials(api_key_id="key", api_key_secret="secret", api_base="https://example.com"),
            )
        _, kwargs = client_factory.call_args
        self.assertIsInstance(kwargs["verify"], ssl.SSLContext)
        self.assertFalse(kwargs["trust_env"])

    def test_request_retries_retryable_http_status(self) -> None:
        client = CoinbaseAdvancedClient(
            CoinbaseCredentials(api_key_id="key", api_key_secret="secret", api_base="https://example.com"),
            max_retries=2,
            retry_backoff_seconds=0,
        )
        client.auth = type("Auth", (), {"bearer_for_rest": lambda self, method, path: "token"})()
        request = httpx.Request("GET", "https://example.com/test")
        with patch.object(
            client._client,
            "request",
            side_effect=[
                httpx.Response(502, request=request),
                httpx.Response(200, request=request, json={"ok": True}),
            ],
        ) as request_mock:
            payload = client._request("GET", "/test")
        self.assertEqual(payload, {"ok": True})
        self.assertEqual(request_mock.call_count, 2)
        client.close()

    def test_request_rebuilds_client_after_request_error(self) -> None:
        client = CoinbaseAdvancedClient(
            CoinbaseCredentials(api_key_id="key", api_key_secret="secret", api_base="https://example.com"),
            max_retries=1,
            retry_backoff_seconds=0,
        )
        client.auth = type("Auth", (), {"bearer_for_rest": lambda self, method, path: "token"})()
        request = httpx.Request("GET", "https://example.com/test")
        first_transport = Mock()
        first_transport.request.side_effect = httpx.ConnectError("dns failed", request=request)
        second_transport = Mock()
        second_transport.request.return_value = httpx.Response(200, request=request, json={"ok": True})
        first_transport.close = Mock()
        second_transport.close = Mock()
        with patch.object(client, "_build_client", side_effect=[second_transport]):
            client._client = first_transport
            payload = client._request("GET", "/test")
        self.assertEqual(payload, {"ok": True})
        first_transport.close.assert_called_once()
        second_transport.request.assert_called_once()
        client.close()


class _FakeIntxClient:
    def __init__(self) -> None:
        self.public_candle_limits: list[int] = []
        self.product_calls = 0
        self.portfolio_calls = 0
        self.balance_calls = 0
        self.position_calls = 0

    def get_product(self, product_id: str):
        self.product_calls += 1
        price = Decimal("2000") if product_id.startswith("ETH") else Decimal("90000")
        return type(
            "Snapshot",
            (),
            {
                "price": price,
                "raw": {
                    "future_product_details": {
                        "index_price": str(price),
                        "perpetual_details": {"funding_rate": "0.0001", "open_interest": "1000", "max_leverage": "5"},
                    },
                    "mid_market_price": str(price),
                    "approximate_quote_24h_volume": "100000",
                },
            },
        )()

    def get_public_candles(self, product_id: str, *, start: int, end: int, granularity: str, limit: int | None = None):
        assert limit is not None
        self.public_candle_limits.append(limit)
        step = 900
        return [
            Candle(
                start=start + (index * step),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
                volume=Decimal("10"),
            )
            for index in range(limit)
        ]

    def get_intx_portfolio(self, portfolio_uuid: str) -> dict:
        self.portfolio_calls += 1
        return {"portfolios": [{"total_balance": "200", "unrealized_pnl": "0"}]}

    def get_intx_balances(self, portfolio_uuid: str) -> dict:
        self.balance_calls += 1
        return {
            "portfolio_balances": [
                {
                    "portfolio_uuid": portfolio_uuid,
                    "balances": [{"asset": {"asset_name": "USDC"}, "max_portfolio_transfer_amount": "120"}],
                }
            ]
        }

    def get_intx_positions(self, portfolio_uuid: str) -> dict:
        self.position_calls += 1
        return {
            "positions": [
                {
                    "product_id": "BTC-PERP-INTX",
                    "net_size": "0.001",
                    "position_side": "LONG",
                    "entry_vwap": "90000",
                    "position_notional": "90",
                    "im_notional": "90",
                    "updated_time": datetime.now(UTC).isoformat(),
                    "unrealized_pnl": "1.2",
                }
            ]
        }


class _FakeIntxTradeClient:
    def __init__(self) -> None:
        self.fail_preview = False
        self.fail_create = False
        self.preview_calls = 0
        self.create_calls = 0
        self.positions: list[dict[str, str]] = []

    def get_product(self, product_id: str) -> ProductSnapshot:
        price = Decimal("90000") if product_id.startswith("BTC") else Decimal("2000")
        return ProductSnapshot(
            product_id=product_id,
            price=price,
            base_increment=Decimal("0.0001"),
            quote_increment=Decimal("0.01"),
            quote_min_size=Decimal("10"),
            base_min_size=Decimal("0.0001"),
            raw={
                "future_product_details": {
                    "index_price": str(price),
                    "perpetual_details": {"funding_rate": "0.0001", "open_interest": "1000", "max_leverage": "5"},
                },
                "mid_market_price": str(price),
                "approximate_quote_24h_volume": "100000",
            },
        )

    def get_intx_portfolio(self, portfolio_uuid: str) -> dict:
        return {"portfolios": [{"total_balance": "200", "unrealized_pnl": "0"}]}

    def get_intx_balances(self, portfolio_uuid: str) -> dict:
        return {
            "portfolio_balances": [
                {
                    "portfolio_uuid": portfolio_uuid,
                    "balances": [{"asset": {"asset_name": "USDC"}, "max_portfolio_transfer_amount": "120"}],
                }
            ]
        }

    def get_intx_positions(self, portfolio_uuid: str) -> dict:
        return {"positions": self.positions}

    def preview_intx_market_order(
        self,
        *,
        portfolio_uuid: str,
        product_id: str,
        side: str,
        base_size: Decimal,
        leverage: Decimal,
        reduce_only: bool,
    ) -> OrderResult:
        self.preview_calls += 1
        if self.fail_preview:
            return OrderResult(
                success=False,
                preview_id=None,
                product_id=product_id,
                side=side,
                message="preview_failed",
                raw={"error_response": {"message": "preview_failed"}},
            )
        return OrderResult(
            success=True,
            preview_id="preview-1",
            product_id=product_id,
            side=side,
            raw={"preview_id": "preview-1"},
        )

    def create_intx_market_order(
        self,
        *,
        portfolio_uuid: str,
        product_id: str,
        side: str,
        base_size: Decimal,
        leverage: Decimal,
        reduce_only: bool,
        preview_id: str | None = None,
    ) -> OrderResult:
        self.create_calls += 1
        if self.fail_create:
            return OrderResult(
                success=False,
                order_id="failed-order",
                product_id=product_id,
                side=side,
                message="order_failed",
                raw={"success": False, "error_response": {"message": "order_failed"}},
            )
        return OrderResult(
            success=True,
            order_id="order-1",
            product_id=product_id,
            side=side,
            raw={"success": True, "success_response": {"order_id": "order-1"}},
        )

    def list_fills(self, *, order_id: str | None = None, product_id: str | None = None) -> list[dict[str, str]]:
        return [
            {
                "order_id": order_id or "order-1",
                "product_id": product_id or "BTC-PERP-INTX",
                "price": "90000",
                "commission": "0.01",
                "size": "0.001",
                "trade_time": "2026-03-03T01:00:00+00:00",
            }
        ]


class CoinbaseIntxEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.tmpdir.name) / "state.db")
        self.client = _FakeIntxClient()
        ctx = CoinbaseIntxContext(
            config=PerpConfig(exchange="coinbase_intx", mode="live", coins=["BTC", "ETH"]),
            client=self.client,  # type: ignore[arg-type]
            state=self.store,
            portfolio_uuid="portfolio-1",
        )
        self.engine = CoinbaseIntxEngine(ctx)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_candles_batches_large_public_history_requests(self) -> None:
        candles = self.engine.candles("BTC", interval="15m", lookback=650)
        self.assertEqual(len(candles), 650)
        self.assertEqual(self.client.public_candle_limits, [300, 300, 50])

    def test_portfolio_and_account_reuse_cached_exchange_payloads(self) -> None:
        portfolio = self.engine.portfolio()
        account_btc = self.engine.account("BTC")
        account_eth = self.engine.account("ETH")
        self.assertEqual(portfolio.available_equity_usd, Decimal("120"))
        self.assertIsNotNone(account_btc.position)
        self.assertIsNone(account_eth.position)
        self.assertEqual(self.client.portfolio_calls, 1)
        self.assertEqual(self.client.balance_calls, 1)
        self.assertEqual(self.client.position_calls, 1)
        self.assertEqual(self.client.product_calls, 2)


class CoinbaseIntxOrderSubmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.tmpdir.name) / "state.db")
        self.client = _FakeIntxTradeClient()
        ctx = CoinbaseIntxContext(
            config=PerpConfig(exchange="coinbase_intx", mode="live", coins=["BTC"]),
            client=self.client,  # type: ignore[arg-type]
            state=self.store,
            portfolio_uuid="portfolio-1",
        )
        self.engine = CoinbaseIntxEngine(ctx)

    def tearDown(self) -> None:
        self.tmpdir.cleanup()

    def test_open_live_failed_create_does_not_record_fill(self) -> None:
        self.client.fail_create = True
        result = self.engine.open_live(side="long", notional_usd=Decimal("20"), leverage=Decimal("2"), coin="BTC")
        self.assertFalse(result.success)
        fills = self.store.list_perp_fills(exchange="coinbase_intx", coin="BTC", limit=10)
        self.assertEqual(fills, [])

    def test_close_paper_failed_create_does_not_record_fill(self) -> None:
        self.client.positions = [
            {
                "product_id": "BTC-PERP-INTX",
                "net_size": "0.001",
                "position_side": "LONG",
                "entry_vwap": "90000",
                "position_notional": "90",
                "im_notional": "45",
                "updated_time": datetime.now(UTC).isoformat(),
                "unrealized_pnl": "0",
            }
        ]
        self.client.fail_create = True
        result = self.engine.close_paper("BTC")
        self.assertFalse(result.success)
        fills = self.store.list_perp_fills(exchange="coinbase_intx", coin="BTC", limit=10)
        self.assertEqual(fills, [])

    def test_open_live_rejects_invalid_side(self) -> None:
        result = self.engine.open_live(side="BUY", notional_usd=Decimal("20"), leverage=Decimal("2"), coin="BTC")  # type: ignore[arg-type]
        self.assertFalse(result.success)
        self.assertEqual(result.message, "invalid_side")
        self.assertEqual(self.client.preview_calls, 0)
        self.assertEqual(self.client.create_calls, 0)


class BuildPerpEngineTests(unittest.TestCase):
    def test_build_perp_engine_reuses_cached_portfolio_uuid(self) -> None:
        runtime = RuntimeConfig(
            app=AppConfig(),
            risk=RiskConfig(),
            news=NewsConfig(),
            perps=PerpConfig(exchange="coinbase_intx"),
            dispatch=DispatchConfig(market_mode="perps"),
            strategy=StrategyConfig(),
            workflow=WorkflowConfig(),
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            store = StateStore(Path(tmpdir) / "state.db")
            fake_client = Mock()
            fake_client.get_key_permissions.return_value = {"portfolio_uuid": "portfolio-1"}
            with patch("openclaw_trader.perps.load_coinbase_credentials", return_value=CoinbaseCredentials("id", "secret")), \
                 patch("openclaw_trader.perps.CoinbaseAdvancedClient", return_value=fake_client) as client_factory:
                build_perp_engine(runtime, store)
                build_perp_engine(runtime, store)
        fake_client.get_key_permissions.assert_called_once_with()
        self.assertEqual(client_factory.call_count, 2)


if __name__ == "__main__":
    unittest.main()
