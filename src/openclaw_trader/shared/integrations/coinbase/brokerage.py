from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from ...protocols.market_types import Balance, OrderResult, ProductSnapshot


class CoinbaseBrokerageMixin:
    def list_accounts(self) -> list[Balance]:
        payload = self._request("GET", "/api/v3/brokerage/accounts")
        balances: list[Balance] = []
        for account in payload.get("accounts", []):
            balances.append(
                Balance(
                    currency=account["currency"],
                    available=Decimal(account["available_balance"]["value"]),
                    hold=Decimal(account.get("hold", {}).get("value", "0")),
                    account_uuid=account.get("uuid"),
                    retail_portfolio_id=account.get("retail_portfolio_id"),
                )
            )
        return balances

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

    def list_orders(self, *, product_id: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if product_id:
            params["product_id"] = product_id
        if limit is not None:
            params["limit"] = limit
        payload = self._request("GET", "/api/v3/brokerage/orders/historical/batch", params=params)
        return list(payload.get("orders") or [])

    def list_fills(self, *, order_id: str | None = None, product_id: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if order_id:
            params["order_id"] = order_id
        if product_id:
            params["product_id"] = product_id
        payload = self._request("GET", "/api/v3/brokerage/orders/historical/fills", params=params)
        return list(payload.get("fills", []) or [])

    def get_key_permissions(self) -> dict[str, Any]:
        return self._request("GET", "/api/v3/brokerage/key_permissions")
