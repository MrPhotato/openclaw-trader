from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_DOWN
from typing import Any

from ....config.loader import load_coinbase_credentials, load_system_settings
from .client import CoinbaseAdvancedClient


def _d(value: object | None, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    if isinstance(value, dict):
        if "value" in value:
            return _d(value.get("value"), default)
        return Decimal(default)
    text = str(value).strip()
    if not text:
        return Decimal(default)
    return Decimal(text)


def _round_down_to_increment(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= 0:
        return value
    steps = (value / increment).to_integral_value(rounding=ROUND_DOWN)
    return steps * increment


@dataclass
class IntxPosition:
    coin: str
    side: str
    quantity: Decimal
    notional_usd: Decimal
    leverage: Decimal
    entry_price: Decimal
    unrealized_pnl: Decimal
    opened_at: datetime
    raw: dict[str, Any]


class CoinbaseIntxRuntimeClient:
    def __init__(self) -> None:
        self.settings = load_system_settings()
        self.credentials = self.settings.coinbase or load_coinbase_credentials(self.settings.runtime_root)
        self.client = CoinbaseAdvancedClient(self.credentials)
        permissions = self.client.get_key_permissions()
        self.portfolio_uuid = str(permissions.get("portfolio_uuid") or "").strip()
        if not self.portfolio_uuid:
            raise ValueError("coinbase intx portfolio_uuid missing from key permissions")
        self._product_cache: dict[str, Any] = {}

    def product_id(self, coin: str) -> str:
        return f"{coin.upper()}-PERP-INTX"

    def product(self, coin: str):
        target = coin.upper()
        if target not in self._product_cache:
            self._product_cache[target] = self.client.get_product(self.product_id(target))
        return self._product_cache[target]

    def snapshot(self, coin: str) -> dict[str, Any]:
        product = self.product(coin)
        details = product.raw.get("future_product_details") or {}
        perp = details.get("perpetual_details") or {}
        index_price = _d(
            perp.get("index_price")
            or details.get("index_price")
            or product.raw.get("index_price")
            or product.raw.get("mid_market_price"),
            default="0",
        )
        premium = None
        if index_price > 0:
            premium = (product.price - index_price) / index_price
        return {
            "coin": coin.upper(),
            "product_id": self.product_id(coin),
            "mark_price": product.price,
            "index_price": index_price if index_price > 0 else None,
            "premium": premium,
            "funding_rate": _d(perp.get("funding_rate")) if perp.get("funding_rate") is not None else None,
            "open_interest": _d(perp.get("open_interest")) if perp.get("open_interest") is not None else None,
            "max_leverage": _d(perp.get("max_leverage")) if perp.get("max_leverage") is not None else None,
            "day_notional_volume": _d(product.raw.get("approximate_quote_24h_volume")) if product.raw.get("approximate_quote_24h_volume") is not None else None,
            "trading_status": product.status,
            "trading_disabled": product.trading_disabled,
            "cancel_only": product.cancel_only,
            "limit_only": product.limit_only,
            "post_only": product.post_only,
            "captured_at": datetime.now(UTC),
            "raw": product.raw,
        }

    def _positions_payload(self) -> list[dict[str, Any]]:
        payload = self.client.get_intx_positions(self.portfolio_uuid)
        return payload.get("positions", []) or []

    def position(self, coin: str) -> IntxPosition | None:
        symbol = self.product_id(coin)
        for payload in self._positions_payload():
            current_symbol = str(payload.get("symbol") or payload.get("product_id") or "").upper()
            if current_symbol != symbol:
                continue
            net_size = _d(payload.get("net_size"))
            if net_size == 0:
                return None
            side = "short" if net_size < 0 or "SHORT" in str(payload.get("position_side") or "").upper() else "long"
            entry_price = _d(payload.get("entry_vwap"), str(self.snapshot(coin)["mark_price"]))
            leverage = _d(payload.get("leverage"), str(self.settings.execution.max_leverage))
            opened_at_raw = payload.get("updated_time") or payload.get("created_time") or datetime.now(UTC).isoformat()
            opened_at = datetime.fromisoformat(str(opened_at_raw).replace("Z", "+00:00"))
            if opened_at.tzinfo is None:
                opened_at = opened_at.replace(tzinfo=UTC)
            return IntxPosition(
                coin=coin.upper(),
                side=side,
                quantity=abs(net_size),
                notional_usd=abs(_d(payload.get("position_notional"), str(abs(net_size) * entry_price))),
                leverage=leverage,
                entry_price=entry_price,
                unrealized_pnl=_d(payload.get("unrealized_pnl")),
                opened_at=opened_at,
                raw=payload,
            )
        return None

    def list_positions(self) -> list[IntxPosition]:
        positions: list[IntxPosition] = []
        for coin in self.settings.execution.supported_coins:
            position = self.position(coin)
            if position is not None:
                positions.append(position)
        return positions

    def portfolio(self) -> dict[str, Any]:
        portfolio_payload = self.client.get_intx_portfolio(self.portfolio_uuid)["portfolios"][0]
        total_equity = _d(portfolio_payload.get("total_balance"))
        unrealized = _d(portfolio_payload.get("unrealized_pnl"))
        available = total_equity
        balances_payload = self.client.get_intx_balances(self.portfolio_uuid).get("portfolio_balances", [])
        for portfolio_balance in balances_payload:
            if str(portfolio_balance.get("portfolio_uuid")) != self.portfolio_uuid:
                continue
            for balance in portfolio_balance.get("balances", []):
                asset = balance.get("asset") or {}
                if str(asset.get("asset_name") or asset.get("asset_id") or "").upper() != "USDC":
                    continue
                available = _d(balance.get("max_portfolio_transfer_amount"), str(total_equity))
                break
        positions = self.list_positions()
        return {
            "starting_equity_usd": str(total_equity - unrealized),
            "realized_pnl_usd": "0",
            "unrealized_pnl_usd": str(unrealized),
            "total_equity_usd": str(total_equity),
            "available_equity_usd": str(available),
            "total_exposure_usd": str(sum((position.notional_usd for position in positions), Decimal("0"))),
            "positions": [
                {
                    "coin": position.coin,
                    "side": position.side,
                    "notional_usd": str(position.notional_usd),
                    "leverage": str(position.leverage),
                    "entry_price": str(position.entry_price),
                    "unrealized_pnl_usd": str(position.unrealized_pnl),
                    "quantity": str(position.quantity),
                    "opened_at": position.opened_at.isoformat(),
                    "raw": position.raw,
                }
                for position in positions
            ],
        }

    def account(self, coin: str) -> dict[str, Any]:
        portfolio = self.portfolio()
        position = self.position(coin)
        snapshot = self.snapshot(coin)
        return {
            "coin": coin.upper(),
            "total_equity_usd": portfolio["total_equity_usd"],
            "available_equity_usd": portfolio["available_equity_usd"],
            "current_side": position.side if position else None,
            "current_notional_usd": str(position.notional_usd) if position else None,
            "current_leverage": str(position.leverage) if position else None,
            "current_quantity": str(position.quantity) if position else None,
            "entry_price": str(position.entry_price) if position else None,
            "unrealized_pnl_usd": str(position.unrealized_pnl) if position else None,
            "liquidation_price": str((position.raw or {}).get("liquidation_price")) if position and (position.raw or {}).get("liquidation_price") is not None else None,
            "mark_price": str(snapshot["mark_price"]),
            "captured_at": datetime.now(UTC).isoformat(),
            "raw": {"portfolio": portfolio, "snapshot": snapshot, "position": position.raw if position else None},
        }

    def _base_size_for_notional(self, coin: str, notional_usd: Decimal) -> tuple[Decimal, Any]:
        product = self.product(coin)
        price = product.price
        base_size = _round_down_to_increment(notional_usd / price, product.base_increment)
        if product.base_min_size is not None and base_size < product.base_min_size:
            base_size = product.base_min_size
        if base_size * price < product.quote_min_size:
            required = _round_down_to_increment(product.quote_min_size / price, product.base_increment)
            if required * price < product.quote_min_size:
                required += product.base_increment
            base_size = max(base_size, required)
        return base_size, product

    def execute_market_order(self, *, coin: str, action: str, side: str, notional_usd: Decimal, leverage: Decimal) -> dict[str, Any]:
        current_position = self.position(coin)
        trade_side = "BUY" if side == "long" else "SELL"
        reduce_only = False
        target_notional = notional_usd
        if action == "close":
            if current_position is None:
                return {"success": False, "message": "no_position_to_close"}
            trade_side = "SELL" if current_position.side == "long" else "BUY"
            reduce_only = True
            target_notional = current_position.notional_usd
        elif action == "reduce":
            if current_position is None:
                return {"success": False, "message": "no_position_to_reduce"}
            trade_side = "SELL" if current_position.side == "long" else "BUY"
            reduce_only = True
            target_notional = min(target_notional, current_position.notional_usd)
        elif action == "flip" and current_position is not None:
            target_notional = current_position.notional_usd + notional_usd

        base_size, product = self._base_size_for_notional(coin, target_notional)
        preview = self.client.preview_intx_market_order(
            portfolio_uuid=self.portfolio_uuid,
            product_id=self.product_id(coin),
            side=trade_side,
            base_size=base_size,
            leverage=leverage,
            reduce_only=reduce_only,
        )
        if not preview.success:
            return {
                "success": False,
                "message": preview.message or "preview_failed",
                "preview": preview.raw,
                "technical_failure": False,
            }
        order = self.client.create_intx_market_order(
            portfolio_uuid=self.portfolio_uuid,
            product_id=self.product_id(coin),
            side=trade_side,
            base_size=base_size,
            leverage=leverage,
            reduce_only=reduce_only,
            preview_id=preview.preview_id,
        )
        fills = self.client.list_fills(order_id=order.order_id, product_id=self.product_id(coin)) if order.order_id else []
        message = order.message or ("submitted" if order.success else "order_failed")
        return {
            "success": order.success,
            "message": message,
            "order_id": order.order_id,
            "preview_id": preview.preview_id,
            "fills": fills,
            "base_size": str(base_size),
            "product": product.raw,
            "technical_failure": (not order.success) and not bool(order.message),
        }
