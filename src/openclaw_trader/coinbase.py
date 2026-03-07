from __future__ import annotations

import ssl
import time
import uuid
from decimal import Decimal
from typing import Any

import certifi
import httpx

from .auth import CoinbaseJwtAuth
from .config import CoinbaseCredentials
from .models import Balance, Candle, OrderResult, ProductSnapshot


class CoinbaseAdvancedClient:
    RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        credentials: CoinbaseCredentials,
        timeout: float = 20.0,
        *,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
    ):
        self.credentials = credentials
        self.auth = CoinbaseJwtAuth(credentials)
        self.base_url = credentials.api_base.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self._client = self._build_client()

    def _build_client(self) -> httpx.Client:
        # Pin CA resolution to certifi and ignore ambient SSL env so launchd
        # processes do not inherit a broken trust store path.
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            verify=ssl_context,
            trust_env=False,
        )

    def _reset_client(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
        self._client = self._build_client()

    def close(self) -> None:
        self._client.close()

    def __del__(self) -> None:  # pragma: no cover - best effort cleanup
        try:
            self.close()
        except Exception:
            pass

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json: dict[str, Any] | None = None) -> dict[str, Any]:
        last_error: httpx.HTTPError | None = None
        for attempt in range(self.max_retries + 1):
            token = self.auth.bearer_for_rest(method, path)
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            try:
                response = self._client.request(method, path, headers=headers, params=params, json=json)
                response.raise_for_status()
                if not response.content:
                    return {}
                return response.json()
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code not in self.RETRYABLE_STATUS_CODES or attempt >= self.max_retries:
                    raise
            except httpx.RequestError as exc:
                last_error = exc
                self._reset_client()
                if attempt >= self.max_retries:
                    raise
            time.sleep(self.retry_backoff_seconds * (2**attempt))
        if last_error is not None:  # pragma: no cover - defensive guard
            raise last_error
        raise RuntimeError(f"coinbase request exhausted retries: {method} {path}")

    def list_accounts(self) -> list[Balance]:
        payload = self._request("GET", "/api/v3/brokerage/accounts")
        out: list[Balance] = []
        for account in payload.get("accounts", []):
            out.append(
                Balance(
                    currency=account["currency"],
                    available=Decimal(account["available_balance"]["value"]),
                    hold=Decimal(account.get("hold", {}).get("value", "0")),
                    account_uuid=account.get("uuid"),
                    retail_portfolio_id=account.get("retail_portfolio_id"),
                )
            )
        return out

    def get_product(self, product_id: str) -> ProductSnapshot:
        payload = self._request("GET", f"/api/v3/brokerage/products/{product_id}")
        quote_max = payload.get("quote_max_size")
        base_min = payload.get("base_min_size")
        base_max = payload.get("base_max_size")
        return ProductSnapshot(
            product_id=payload["product_id"],
            price=Decimal(payload["price"]),
            base_increment=Decimal(payload["base_increment"]),
            quote_increment=Decimal(payload["quote_increment"]),
            quote_min_size=Decimal(payload["quote_min_size"]),
            quote_max_size=Decimal(quote_max) if quote_max else None,
            base_min_size=Decimal(base_min) if base_min else None,
            base_max_size=Decimal(base_max) if base_max else None,
            status=payload.get("status"),
            trading_disabled=payload.get("trading_disabled", False),
            cancel_only=payload.get("cancel_only", False),
            limit_only=payload.get("limit_only", False),
            post_only=payload.get("post_only", False),
            raw=payload,
        )

    def get_candles(self, product_id: str, *, start: int, end: int, granularity: str, limit: int | None = None) -> list[Candle]:
        params: dict[str, Any] = {
            "start": str(start),
            "end": str(end),
            "granularity": granularity,
        }
        if limit is not None:
            params["limit"] = limit
        payload = self._request("GET", f"/api/v3/brokerage/products/{product_id}/candles", params=params)
        candles = [Candle(**candle) for candle in payload.get("candles", [])]
        return sorted(candles, key=lambda c: c.start)

    def get_public_candles(self, product_id: str, *, start: int, end: int, granularity: str, limit: int | None = None) -> list[Candle]:
        params: dict[str, Any] = {
            "start": str(start),
            "end": str(end),
            "granularity": granularity,
        }
        if limit is not None:
            params["limit"] = limit
        payload = self._request("GET", f"/api/v3/brokerage/market/products/{product_id}/candles", params=params)
        candles = [Candle(**candle) for candle in payload.get("candles", [])]
        return sorted(candles, key=lambda c: c.start)

    def preview_market_order(self, *, product_id: str, side: str, quote_size: Decimal | None = None, base_size: Decimal | None = None) -> OrderResult:
        order_config: dict[str, Any] = {"market_market_ioc": {}}
        if quote_size is not None:
            order_config["market_market_ioc"]["quote_size"] = f"{quote_size:f}"
        if base_size is not None:
            order_config["market_market_ioc"]["base_size"] = f"{base_size:f}"
        payload = self._request(
            "POST",
            "/api/v3/brokerage/orders/preview",
            json={
                "product_id": product_id,
                "side": side,
                "order_configuration": order_config,
            },
        )
        return OrderResult(
            success=bool(payload.get("preview_id")),
            preview_id=payload.get("preview_id"),
            product_id=product_id,
            side=side,
            message=payload.get("error_response", {}).get("message"),
            raw=payload,
        )

    def create_market_order(self, *, product_id: str, side: str, quote_size: Decimal | None = None, base_size: Decimal | None = None, preview_id: str | None = None) -> OrderResult:
        order_config: dict[str, Any] = {"market_market_ioc": {}}
        if quote_size is not None:
            order_config["market_market_ioc"]["quote_size"] = f"{quote_size:f}"
        if base_size is not None:
            order_config["market_market_ioc"]["base_size"] = f"{base_size:f}"
        body = {
            "client_order_id": str(uuid.uuid4()),
            "product_id": product_id,
            "side": side,
            "order_configuration": order_config,
        }
        if preview_id:
            body["preview_id"] = preview_id
        payload = self._request("POST", "/api/v3/brokerage/orders", json=body)
        success_response = payload.get("success_response", {})
        error_response = payload.get("error_response", {})
        return OrderResult(
            success=payload.get("success", False),
            order_id=success_response.get("order_id"),
            product_id=success_response.get("product_id") or product_id,
            side=success_response.get("side") or side,
            message=error_response.get("message"),
            raw=payload,
        )

    def get_order(self, order_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v3/brokerage/orders/historical/{order_id}")

    def list_fills(self, *, order_id: str | None = None, product_id: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if order_id:
            params["order_id"] = order_id
        if product_id:
            params["product_id"] = product_id
        payload = self._request("GET", "/api/v3/brokerage/orders/historical/fills", params=params)
        return payload.get("fills", [])

    def get_key_permissions(self) -> dict[str, Any]:
        return self._request("GET", "/api/v3/brokerage/key_permissions")

    def get_intx_portfolio(self, portfolio_uuid: str) -> dict[str, Any]:
        payload = self._request("GET", f"/api/v3/brokerage/intx/portfolio/{portfolio_uuid}")
        portfolios = payload.get("portfolios", [])
        if not portfolios:
            raise ValueError(f"INTX portfolio not found: {portfolio_uuid}")
        return payload

    def get_intx_balances(self, portfolio_uuid: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v3/brokerage/intx/balances/{portfolio_uuid}")

    def get_intx_positions(self, portfolio_uuid: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v3/brokerage/intx/positions/{portfolio_uuid}")

    def preview_intx_market_order(
        self,
        *,
        portfolio_uuid: str,
        product_id: str,
        side: str,
        base_size: Decimal,
        leverage: Decimal,
        margin_type: str = "CROSS",
        reduce_only: bool = False,
    ) -> OrderResult:
        payload = self._request(
            "POST",
            "/api/v3/brokerage/orders/preview",
            json={
                "product_id": product_id,
                "side": side,
                "retail_portfolio_id": portfolio_uuid,
                "leverage": f"{leverage:f}",
                "margin_type": margin_type,
                "order_configuration": {
                    "market_market_ioc": {
                        "base_size": f"{base_size:f}",
                        "reduce_only": reduce_only,
                    }
                },
            },
        )
        return OrderResult(
            success=bool(payload.get("preview_id")),
            preview_id=payload.get("preview_id"),
            product_id=product_id,
            side=side,
            message=payload.get("error_response", {}).get("message"),
            raw=payload,
        )

    def create_intx_market_order(
        self,
        *,
        portfolio_uuid: str,
        product_id: str,
        side: str,
        base_size: Decimal,
        leverage: Decimal,
        margin_type: str = "CROSS",
        reduce_only: bool = False,
        preview_id: str | None = None,
    ) -> OrderResult:
        body: dict[str, Any] = {
            "client_order_id": str(uuid.uuid4()),
            "product_id": product_id,
            "side": side,
            "retail_portfolio_id": portfolio_uuid,
            "leverage": f"{leverage:f}",
            "margin_type": margin_type,
            "order_configuration": {
                "market_market_ioc": {
                    "base_size": f"{base_size:f}",
                    "reduce_only": reduce_only,
                }
            },
        }
        if preview_id:
            body["preview_id"] = preview_id
        payload = self._request("POST", "/api/v3/brokerage/orders", json=body)
        success_response = payload.get("success_response", {})
        error_response = payload.get("error_response", {})
        return OrderResult(
            success=payload.get("success", False),
            order_id=success_response.get("order_id"),
            product_id=success_response.get("product_id") or product_id,
            side=success_response.get("side") or side,
            message=error_response.get("message"),
            raw=payload,
        )
