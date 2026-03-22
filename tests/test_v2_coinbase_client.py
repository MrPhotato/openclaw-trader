from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import Mock, patch

import httpx

from openclaw_trader.config.models import CoinbaseCredentials
from openclaw_trader.shared.integrations.coinbase import CoinbaseAdvancedClient


class CoinbaseAdvancedClientTests(unittest.TestCase):
    def test_client_uses_certifi_and_ignores_ambient_ssl_env(self) -> None:
        with patch("openclaw_trader.shared.integrations.coinbase.transport.httpx.Client") as client_factory:
            CoinbaseAdvancedClient(
                CoinbaseCredentials(api_key_id="key", api_key_secret="secret", api_base="https://example.com"),
            )
        _, kwargs = client_factory.call_args
        import ssl

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

    def test_public_candles_use_stronger_retry_budget_for_request_errors(self) -> None:
        client = CoinbaseAdvancedClient(
            CoinbaseCredentials(api_key_id="key", api_key_secret="secret", api_base="https://example.com"),
            max_retries=1,
            retry_backoff_seconds=0,
        )
        client.auth = type("Auth", (), {"bearer_for_rest": lambda self, method, path: "token"})()
        request = httpx.Request("GET", "https://example.com/api/v3/brokerage/market/products/BTC-PERP-INTX/candles")
        first_transport = Mock()
        first_transport.request.side_effect = httpx.ConnectError("dns failed", request=request)
        first_transport.close = Mock()
        second_transport = Mock()
        second_transport.request.side_effect = httpx.ConnectError("dns failed", request=request)
        second_transport.close = Mock()
        third_transport = Mock()
        third_transport.request.side_effect = httpx.ConnectError("dns failed", request=request)
        third_transport.close = Mock()
        fourth_transport = Mock()
        fourth_transport.request.return_value = httpx.Response(
            200,
            request=request,
            json={"candles": [{"start": 1, "low": "1", "high": "2", "open": "1.5", "close": "1.8", "volume": "10"}]},
        )
        fourth_transport.close = Mock()
        with patch.object(client, "_build_client", side_effect=[second_transport, third_transport, fourth_transport]):
            client._client = first_transport
            candles = client.get_public_candles("BTC-PERP-INTX", start=0, end=60, granularity="ONE_MINUTE", limit=1)
        self.assertEqual(len(candles), 1)
        self.assertEqual(first_transport.request.call_count, 1)
        self.assertEqual(second_transport.request.call_count, 1)
        self.assertEqual(third_transport.request.call_count, 1)
        self.assertEqual(fourth_transport.request.call_count, 1)
        client.close()

    def test_intx_summary_and_balances_use_current_paths(self) -> None:
        client = CoinbaseAdvancedClient(
            CoinbaseCredentials(api_key_id="key", api_key_secret="secret", api_base="https://example.com"),
        )
        with patch.object(client, "_request", return_value={"ok": True}) as request_mock:
            client.get_intx_portfolio("portfolio-123")
            client.get_intx_balances("portfolio-123")
            client.get_intx_positions("portfolio-123")

        self.assertEqual(request_mock.call_args_list[0].args, ("GET", "/api/v3/brokerage/intx/portfolio/portfolio-123"))
        self.assertEqual(request_mock.call_args_list[1].args, ("GET", "/api/v3/brokerage/intx/balances/portfolio-123"))
        self.assertEqual(request_mock.call_args_list[2].args, ("GET", "/api/v3/brokerage/intx/positions/portfolio-123"))
        client.close()

    def test_intx_orders_use_generic_advanced_trade_endpoints(self) -> None:
        client = CoinbaseAdvancedClient(
            CoinbaseCredentials(api_key_id="key", api_key_secret="secret", api_base="https://example.com"),
        )
        responses = [
            {"preview_id": "preview-1", "errs": []},
            {"success": True, "success_response": {"order_id": "order-1", "product_id": "BTC-PERP-INTX", "side": "BUY"}},
        ]
        with patch.object(client, "_request", side_effect=responses) as request_mock:
            preview = client.preview_intx_market_order(
                portfolio_uuid="portfolio-123",
                product_id="BTC-PERP-INTX",
                side="BUY",
                base_size=Decimal("0.0002"),
                leverage=Decimal("1"),
                reduce_only=False,
            )
            order = client.create_intx_market_order(
                portfolio_uuid="portfolio-123",
                product_id="BTC-PERP-INTX",
                side="BUY",
                base_size=Decimal("0.0002"),
                leverage=Decimal("1"),
                reduce_only=True,
                preview_id="preview-1",
            )

        preview_call = request_mock.call_args_list[0]
        create_call = request_mock.call_args_list[1]
        self.assertEqual(preview_call.args, ("POST", "/api/v3/brokerage/orders/preview"))
        self.assertEqual(preview_call.kwargs["json"]["product_id"], "BTC-PERP-INTX")
        self.assertEqual(preview_call.kwargs["json"]["leverage"], "1")
        self.assertFalse(preview_call.kwargs["json"]["order_configuration"]["market_market_ioc"]["reduce_only"])
        self.assertNotIn("portfolio_uuid", preview_call.kwargs["json"])
        self.assertEqual(create_call.args, ("POST", "/api/v3/brokerage/orders"))
        self.assertEqual(create_call.kwargs["json"]["preview_id"], "preview-1")
        self.assertEqual(create_call.kwargs["json"]["leverage"], "1")
        self.assertTrue(create_call.kwargs["json"]["order_configuration"]["market_market_ioc"]["reduce_only"])
        self.assertNotIn("portfolio_uuid", create_call.kwargs["json"])
        self.assertTrue(preview.success)
        self.assertTrue(order.success)
        client.close()


if __name__ == "__main__":
    unittest.main()
