from __future__ import annotations

import uuid
from decimal import Decimal

from ...protocols.market_types import OrderResult


class CoinbaseIntxApiMixin:
    def get_intx_portfolio(self, portfolio_uuid: str) -> dict[str, object]:
        return self._request("GET", f"/api/v3/brokerage/intx/portfolio/{portfolio_uuid}")

    def get_intx_portfolios(self, portfolio_uuid: str | None = None) -> dict[str, object]:
        if not portfolio_uuid:
            portfolio_uuid = str(self.get_key_permissions().get("portfolio_uuid") or "").strip()
        if not portfolio_uuid:
            raise ValueError("coinbase intx portfolio_uuid missing from key permissions")
        return self.get_intx_portfolio(portfolio_uuid)

    def get_intx_balances(self, portfolio_uuid: str) -> dict[str, object]:
        return self._request("GET", f"/api/v3/brokerage/intx/balances/{portfolio_uuid}")

    def get_intx_positions(self, portfolio_uuid: str) -> dict[str, object]:
        return self._request("GET", f"/api/v3/brokerage/intx/positions/{portfolio_uuid}")

    def preview_intx_market_order(
        self,
        *,
        portfolio_uuid: str,
        product_id: str,
        side: str,
        base_size: Decimal,
        leverage: Decimal,
        reduce_only: bool = False,
    ) -> OrderResult:
        payload = self._request(
            "POST",
            "/api/v3/brokerage/orders/preview",
            json={
                "product_id": product_id,
                "side": side,
                "order_configuration": {
                    "market_market_ioc": {
                        "base_size": f"{base_size:f}",
                        "reduce_only": reduce_only,
                    }
                },
                "leverage": f"{leverage:f}",
            },
        )
        message = payload.get("error_response", {}).get("message") or (payload.get("errs") or [None])[0]
        return OrderResult(
            success=bool(payload.get("preview_id")) and not bool(message),
            preview_id=payload.get("preview_id"),
            product_id=product_id,
            side=side,
            message=message,
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
        reduce_only: bool = False,
        preview_id: str | None = None,
    ) -> OrderResult:
        body = {
            "client_order_id": str(uuid.uuid4()),
            "product_id": product_id,
            "side": side,
            "order_configuration": {
                "market_market_ioc": {
                    "base_size": f"{base_size:f}",
                    "reduce_only": reduce_only,
                }
            },
            "leverage": f"{leverage:f}",
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
