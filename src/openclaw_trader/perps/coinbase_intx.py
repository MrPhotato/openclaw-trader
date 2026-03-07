from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_DOWN
from typing import Any, Literal

from ..coinbase import CoinbaseAdvancedClient
from ..config import PerpConfig
from ..models import PerpPaperAccount, PerpPaperOrderResult, PerpPaperPortfolio, PerpPaperPosition, PerpSnapshot, ProductSnapshot
from ..state import StateStore


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
class CoinbaseIntxContext:
    config: PerpConfig
    client: CoinbaseAdvancedClient
    state: StateStore
    portfolio_uuid: str


class CoinbaseIntxEngine:
    MAX_PUBLIC_CANDLES_PER_REQUEST = 300

    def __init__(self, ctx: CoinbaseIntxContext) -> None:
        self.ctx = ctx
        self._portfolio_payload_cache: dict[str, Any] | None = None
        self._balances_payload_cache: list[dict[str, Any]] | None = None
        self._positions_payload_cache: list[dict[str, Any]] | None = None
        self._portfolio_cache: PerpPaperPortfolio | None = None
        self._product_cache: dict[str, ProductSnapshot] = {}
        self._snapshot_cache: dict[str, PerpSnapshot] = {}
        self._position_cache: dict[str, PerpPaperPosition | None] = {}
        self._account_cache: dict[str, PerpPaperAccount] = {}

    def _coin(self, coin: str | None = None) -> str:
        return (coin or self.ctx.config.coin).upper()

    def _coins(self) -> list[str]:
        coins = [coin.upper() for coin in (self.ctx.config.coins or [self.ctx.config.coin])]
        return list(dict.fromkeys(coins))

    def _product_id(self, coin: str | None = None) -> str:
        return f"{self._coin(coin)}-PERP-INTX"

    def _starting_equity_key(self) -> str:
        return f"perp:{self.ctx.config.exchange}:live_starting_equity_usd:{self.ctx.portfolio_uuid}"

    def _invalidate_runtime_cache(self) -> None:
        self._portfolio_payload_cache = None
        self._balances_payload_cache = None
        self._positions_payload_cache = None
        self._portfolio_cache = None
        self._product_cache.clear()
        self._snapshot_cache.clear()
        self._position_cache.clear()
        self._account_cache.clear()

    def _product(self, coin: str | None = None) -> ProductSnapshot:
        target = self._coin(coin)
        cached = self._product_cache.get(target)
        if cached is not None:
            return cached
        product = self.ctx.client.get_product(self._product_id(target))
        self._product_cache[target] = product
        return product

    def _current_portfolio_payload(self) -> dict[str, Any]:
        if self._portfolio_payload_cache is None:
            self._portfolio_payload_cache = self.ctx.client.get_intx_portfolio(self.ctx.portfolio_uuid)["portfolios"][0]
        return self._portfolio_payload_cache

    def _portfolio_balances_payload(self) -> list[dict[str, Any]]:
        if self._balances_payload_cache is None:
            payload = self.ctx.client.get_intx_balances(self.ctx.portfolio_uuid)
            self._balances_payload_cache = payload.get("portfolio_balances", [])
        return self._balances_payload_cache

    def _positions_payload(self) -> list[dict[str, Any]]:
        if self._positions_payload_cache is None:
            payload = self.ctx.client.get_intx_positions(self.ctx.portfolio_uuid)
            self._positions_payload_cache = payload.get("positions", []) or []
        return self._positions_payload_cache

    def snapshot(self, coin: str | None = None) -> PerpSnapshot:
        target = self._coin(coin)
        cached = self._snapshot_cache.get(target)
        if cached is not None:
            return cached
        product = self._product(target)
        details = product.raw.get("future_product_details") or {}
        perp = details.get("perpetual_details") or {}
        snapshot = PerpSnapshot(
            exchange=self.ctx.config.exchange,
            coin=target,
            mark_price=product.price,
            oracle_price=_d(details.get("index_price"), str(product.price)),
            mid_price=_d(product.raw.get("mid_market_price"), str(product.price)) if product.raw.get("mid_market_price") is not None else None,
            funding_rate=_d(perp.get("funding_rate")) if perp.get("funding_rate") is not None else None,
            premium=None,
            open_interest=_d(perp.get("open_interest")) if perp.get("open_interest") is not None else None,
            max_leverage=_d(perp.get("max_leverage")) if perp.get("max_leverage") is not None else None,
            day_notional_volume=_d(product.raw.get("approximate_quote_24h_volume")) if product.raw.get("approximate_quote_24h_volume") is not None else None,
            raw=product.raw,
        )
        self._snapshot_cache[target] = snapshot
        return snapshot

    def candles(self, coin: str | None = None, interval: str = "15m", lookback: int = 48):
        granularity = {
            "1m": "ONE_MINUTE",
            "5m": "FIVE_MINUTE",
            "15m": "FIFTEEN_MINUTE",
            "30m": "THIRTY_MINUTE",
            "1h": "ONE_HOUR",
            "2h": "TWO_HOUR",
            "6h": "SIX_HOUR",
            "1d": "ONE_DAY",
        }.get(interval, "FIFTEEN_MINUTE")
        interval_seconds = {
            "ONE_MINUTE": 60,
            "FIVE_MINUTE": 300,
            "FIFTEEN_MINUTE": 900,
            "THIRTY_MINUTE": 1800,
            "ONE_HOUR": 3600,
            "TWO_HOUR": 7200,
            "SIX_HOUR": 21600,
            "ONE_DAY": 86400,
        }[granularity]
        end = int(datetime.now(UTC).timestamp())
        product_id = self._product_id(coin)
        if lookback <= self.MAX_PUBLIC_CANDLES_PER_REQUEST:
            start = end - (lookback * interval_seconds)
            return self.ctx.client.get_public_candles(product_id, start=start, end=end, granularity=granularity, limit=lookback)

        candles_by_start: dict[int, Any] = {}
        remaining = lookback
        window_end = end
        while remaining > 0:
            batch_size = min(remaining, self.MAX_PUBLIC_CANDLES_PER_REQUEST)
            window_start = window_end - (batch_size * interval_seconds)
            batch = self.ctx.client.get_public_candles(
                product_id,
                start=window_start,
                end=window_end,
                granularity=granularity,
                limit=batch_size,
            )
            for candle in batch:
                candles_by_start[candle.start] = candle
            if not batch:
                break
            remaining -= batch_size
            window_end = window_start
        return sorted(candles_by_start.values(), key=lambda item: item.start)[-lookback:]

    def _parse_position(self, coin: str, payload: dict[str, Any]) -> PerpPaperPosition | None:
        symbol = str(payload.get("symbol") or payload.get("product_id") or "").upper()
        if symbol and symbol != self._product_id(coin):
            return None
        net_size = _d(payload.get("net_size"))
        if net_size == 0:
            return None
        position_side = str(payload.get("position_side") or "").upper()
        side: Literal["long", "short"] = "short" if "SHORT" in position_side or net_size < 0 else "long"
        quantity = abs(net_size)
        leverage = _d(payload.get("leverage"), str(self.ctx.config.max_leverage))
        entry_price = _d(payload.get("entry_vwap"), str(self.snapshot(coin).mark_price))
        notional = abs(_d(payload.get("position_notional"), str(quantity * entry_price)))
        margin_used = _d(payload.get("im_notional"), str(notional / leverage if leverage > 0 else notional))
        opened_at_raw = payload.get("updated_time") or payload.get("created_time") or datetime.now(UTC).isoformat()
        try:
            opened_at = datetime.fromisoformat(str(opened_at_raw).replace("Z", "+00:00"))
        except Exception:
            opened_at = datetime.now(UTC)
        if opened_at.tzinfo is None:
            opened_at = opened_at.replace(tzinfo=UTC)
        return PerpPaperPosition(
            exchange=self.ctx.config.exchange,
            coin=coin,
            side=side,
            notional_usd=notional,
            leverage=leverage,
            entry_price=entry_price,
            quantity=quantity,
            margin_used_usd=margin_used,
            opened_at=opened_at,
            raw=payload,
        )

    def position(self, coin: str | None = None) -> PerpPaperPosition | None:
        target = self._coin(coin)
        if target in self._position_cache:
            return self._position_cache[target]
        for payload in self._positions_payload():
            parsed = self._parse_position(target, payload)
            if parsed is not None:
                self._position_cache[target] = parsed
                return parsed
        self._position_cache[target] = None
        return None

    def list_positions(self) -> list[PerpPaperPosition]:
        positions: list[PerpPaperPosition] = []
        for coin in self._coins():
            position = self.position(coin)
            if position is not None:
                positions.append(position)
        return positions

    def portfolio(self) -> PerpPaperPortfolio:
        if self._portfolio_cache is not None:
            return self._portfolio_cache
        raw = self._current_portfolio_payload()
        total_equity = _d(raw.get("total_balance"))
        unrealized = _d(raw.get("unrealized_pnl"))
        positions = self.list_positions()
        total_exposure = sum((position.notional_usd for position in positions), Decimal("0"))
        available = total_equity
        for portfolio_payload in self._portfolio_balances_payload():
            if str(portfolio_payload.get("portfolio_uuid")) != self.ctx.portfolio_uuid:
                continue
            for balance in portfolio_payload.get("balances", []):
                asset = balance.get("asset") or {}
                if str(asset.get("asset_name") or asset.get("asset_id") or "").upper() != "USDC":
                    continue
                available = _d(balance.get("max_portfolio_transfer_amount"), str(total_equity))
                break
        starting_raw = self.ctx.state.get_value(self._starting_equity_key())
        if starting_raw is None:
            self.ctx.state.set_value(self._starting_equity_key(), str(total_equity))
            starting = total_equity
        else:
            starting = _d(starting_raw, str(total_equity))
        realized = total_equity - starting - unrealized
        portfolio = PerpPaperPortfolio(
            exchange=self.ctx.config.exchange,
            starting_equity_usd=starting,
            realized_pnl_usd=realized,
            unrealized_pnl_usd=unrealized,
            total_equity_usd=total_equity,
            available_equity_usd=available,
            total_exposure_usd=total_exposure,
            positions=positions,
        )
        self._portfolio_cache = portfolio
        return portfolio

    def account(self, coin: str | None = None) -> PerpPaperAccount:
        target = self._coin(coin)
        cached = self._account_cache.get(target)
        if cached is not None:
            return cached
        portfolio = self.portfolio()
        position = self.position(target)
        snapshot = self.snapshot(target)
        unrealized = _d(position.raw.get("unrealized_pnl"), "0") if position is not None else Decimal("0")
        account = PerpPaperAccount(
            exchange=self.ctx.config.exchange,
            coin=target,
            starting_equity_usd=portfolio.starting_equity_usd,
            realized_pnl_usd=portfolio.realized_pnl_usd,
            unrealized_pnl_usd=unrealized,
            total_equity_usd=portfolio.total_equity_usd,
            available_equity_usd=portfolio.available_equity_usd,
            position=position,
            mark_price=snapshot.mark_price,
        )
        self._account_cache[target] = account
        return account

    def minimum_trade_notional_usd(self, coin: str | None = None) -> Decimal:
        return self._product(coin).quote_min_size

    def _effective_leverage(self, leverage: Decimal | None) -> Decimal:
        target = leverage or Decimal(str(self.ctx.config.max_leverage))
        return min(target, Decimal(str(self.ctx.config.max_leverage)))

    def _base_size_for_notional(self, coin: str, notional_usd: Decimal):
        product = self._product(coin)
        price = product.price
        base_size = _round_down_to_increment(notional_usd / price, product.base_increment)
        if product.base_min_size is not None and base_size < product.base_min_size:
            base_size = product.base_min_size
        if base_size * price < product.quote_min_size:
            required = _round_down_to_increment(product.quote_min_size / price, product.base_increment)
            if required * price < product.quote_min_size:
                required += product.base_increment
            base_size = max(base_size, required)
        return base_size, self.snapshot(coin), product

    def _record_order(self, order) -> None:
        self.ctx.state.record_order(order)

    def _record_fill(
        self,
        *,
        coin: str,
        action: str,
        side: str | None,
        notional_usd: Decimal | None,
        leverage: Decimal | None,
        price: Decimal | None,
        realized_pnl_usd: Decimal | None,
        payload: dict[str, Any],
    ) -> None:
        self.ctx.state.record_perp_paper_fill(
            exchange=self.ctx.config.exchange,
            coin=coin,
            action=action,
            side=side,
            notional_usd=str(notional_usd) if notional_usd is not None else None,
            leverage=str(leverage) if leverage is not None else None,
            price=str(price) if price is not None else None,
            realized_pnl_usd=str(realized_pnl_usd) if realized_pnl_usd is not None else None,
            payload=payload,
        )

    def _submit_market_order(
        self,
        *,
        coin: str,
        trade_side: Literal["BUY", "SELL"],
        notional_usd: Decimal,
        leverage: Decimal,
        reduce_only: bool,
        action: Literal["open_live", "add", "reduce"],
        side_label: Literal["long", "short"],
    ) -> PerpPaperOrderResult:
        base_size, snapshot, product = self._base_size_for_notional(coin, notional_usd)
        preview = self.ctx.client.preview_intx_market_order(
            portfolio_uuid=self.ctx.portfolio_uuid,
            product_id=self._product_id(coin),
            side=trade_side,
            base_size=base_size,
            leverage=leverage,
            reduce_only=reduce_only,
        )
        if not preview.success:
            self._record_order(preview)
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action=action,
                side=side_label,
                notional_usd=notional_usd,
                leverage=leverage,
                message=preview.message,
                raw=preview.raw,
            )
        order = self.ctx.client.create_intx_market_order(
            portfolio_uuid=self.ctx.portfolio_uuid,
            product_id=self._product_id(coin),
            side=trade_side,
            base_size=base_size,
            leverage=leverage,
            reduce_only=reduce_only,
            preview_id=preview.preview_id,
        )
        self._record_order(order)
        fills = self.ctx.client.list_fills(order_id=order.order_id, product_id=self._product_id(coin)) if order.order_id else []
        fill_price = _d(fills[0].get("price")) if fills else snapshot.mark_price
        actual_notional = base_size * fill_price
        payload = {"preview": preview.raw, "order": order.raw, "fills": fills, "base_size": str(base_size), "product": product.raw}
        if not order.success:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action=action,
                side=side_label,
                notional_usd=notional_usd,
                leverage=leverage,
                price=fill_price,
                message=order.message or "coinbase_intx_order_failed",
                raw=payload,
            )
        self._record_fill(
            coin=coin,
            action=action,
            side=side_label,
            notional_usd=actual_notional,
            leverage=leverage,
            price=fill_price,
            realized_pnl_usd=None,
            payload=payload,
        )
        self._invalidate_runtime_cache()
        return PerpPaperOrderResult(
            success=order.success,
            exchange=self.ctx.config.exchange,
            coin=coin,
            action=action,
            side=side_label,
            notional_usd=actual_notional,
            leverage=leverage,
            price=fill_price,
            message=order.message or "coinbase_intx_order_submitted",
            raw=payload,
        )

    def open_paper(
        self,
        *,
        side: Literal["long", "short"],
        notional_usd: Decimal,
        leverage: Decimal | None = None,
        coin: str | None = None,
    ) -> PerpPaperOrderResult:
        if self.ctx.config.mode.value != "live" or not self.ctx.config.live_enabled:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=self._coin(coin),
                action="open",
                side=side,
                notional_usd=notional_usd,
                leverage=leverage,
                message="coinbase_intx_live_disabled",
            )
        if self.position(coin) is not None:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=self._coin(coin),
                action="open",
                side=side,
                notional_usd=notional_usd,
                leverage=leverage,
                message="live_position_already_open",
            )
        return self.open_live(side=side, notional_usd=notional_usd, leverage=leverage, coin=coin)

    def add_paper(
        self,
        *,
        side: Literal["long", "short"],
        notional_usd: Decimal,
        leverage: Decimal | None = None,
        coin: str | None = None,
    ) -> PerpPaperOrderResult:
        target = self._coin(coin)
        position = self.position(target)
        if position is None:
            return self.open_paper(side=side, notional_usd=notional_usd, leverage=leverage, coin=target)
        if position.side != side:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=target,
                action="add",
                side=side,
                notional_usd=notional_usd,
                leverage=leverage,
                message="live_position_side_conflict",
            )
        return self._submit_market_order(
            coin=target,
            trade_side="BUY" if side == "long" else "SELL",
            notional_usd=notional_usd,
            leverage=self._effective_leverage(leverage),
            reduce_only=False,
            action="add",
            side_label=side,
        )

    def reduce_paper(self, *, notional_usd: Decimal, coin: str | None = None) -> PerpPaperOrderResult:
        target = self._coin(coin)
        position = self.position(target)
        if position is None:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=target,
                action="reduce",
                message="no_open_live_position",
            )
        if notional_usd <= 0:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=target,
                action="reduce",
                side=position.side,
                notional_usd=notional_usd,
                leverage=position.leverage,
                message="invalid_reduce_notional",
            )
        if notional_usd >= position.notional_usd:
            return self.close_paper(target)
        trade_side = "BUY" if position.side == "short" else "SELL"
        return self._submit_market_order(
            coin=target,
            trade_side=trade_side,
            notional_usd=notional_usd,
            leverage=position.leverage,
            reduce_only=True,
            action="reduce",
            side_label=position.side,
        )

    def close_paper(self, coin: str | None = None) -> PerpPaperOrderResult:
        target = self._coin(coin)
        position = self.position(target)
        if position is None:
            return PerpPaperOrderResult(success=False, exchange=self.ctx.config.exchange, coin=target, action="close", message="no_open_live_position")
        side = "BUY" if position.side == "short" else "SELL"
        preview = self.ctx.client.preview_intx_market_order(
            portfolio_uuid=self.ctx.portfolio_uuid,
            product_id=self._product_id(target),
            side=side,
            base_size=position.quantity,
            leverage=position.leverage,
            reduce_only=True,
        )
        if not preview.success:
            self._record_order(preview)
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=target,
                action="close",
                side=position.side,
                notional_usd=position.notional_usd,
                leverage=position.leverage,
                message=preview.message,
                raw=preview.raw,
            )
        order = self.ctx.client.create_intx_market_order(
            portfolio_uuid=self.ctx.portfolio_uuid,
            product_id=self._product_id(target),
            side=side,
            base_size=position.quantity,
            leverage=position.leverage,
            reduce_only=True,
            preview_id=preview.preview_id,
        )
        self._record_order(order)
        fills = self.ctx.client.list_fills(order_id=order.order_id, product_id=self._product_id(target)) if order.order_id else []
        fill_price = _d(fills[0].get("price")) if fills else self.snapshot(target).mark_price
        realized = _d(fills[0].get("commission")) * Decimal("-1") if fills else None
        payload = {"preview": preview.raw, "order": order.raw, "fills": fills}
        if not order.success:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=target,
                action="close",
                side=position.side,
                notional_usd=position.notional_usd,
                leverage=position.leverage,
                price=fill_price,
                realized_pnl_usd=realized,
                message=order.message or "coinbase_intx_close_failed",
                raw=payload,
            )
        self._record_fill(
            coin=target,
            action="close",
            side=position.side,
            notional_usd=position.notional_usd,
            leverage=position.leverage,
            price=fill_price,
            realized_pnl_usd=realized,
            payload=payload,
        )
        self._invalidate_runtime_cache()
        return PerpPaperOrderResult(
            success=order.success,
            exchange=self.ctx.config.exchange,
            coin=target,
            action="close",
            side=position.side,
            notional_usd=position.notional_usd,
            leverage=position.leverage,
            price=fill_price,
            realized_pnl_usd=realized,
            message=order.message or "coinbase_intx_position_closed",
            raw=payload,
        )

    def open_live(
        self,
        *,
        side: Literal["long", "short"],
        notional_usd: Decimal,
        leverage: Decimal | None = None,
        coin: str | None = None,
    ) -> PerpPaperOrderResult:
        target = self._coin(coin)
        normalized_side = str(side).strip().lower()
        if normalized_side not in {"long", "short"}:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=target,
                action="open_live",
                side=None,
                notional_usd=notional_usd,
                leverage=leverage,
                message="invalid_side",
            )
        return self._submit_market_order(
            coin=target,
            trade_side="BUY" if normalized_side == "long" else "SELL",
            notional_usd=notional_usd,
            leverage=self._effective_leverage(leverage),
            reduce_only=False,
            action="open_live",
            side_label="long" if normalized_side == "long" else "short",
        )
