from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import mean, pstdev

from .....shared.integrations.coinbase import CoinbaseIntxRuntimeClient
from .....shared.utils import notional_to_pct_of_exposure_budget
from ..models import (
    AccountSnapshot,
    BreakoutRetestState,
    CompressedPriceSeries,
    ExecutionHistorySnapshot,
    KeyLevel,
    LiquiditySnapshot,
    MarketContextNormalized,
    MarketSnapshotNormalized,
    OpenOrderSnapshot,
    OrderbookDepthSnapshot,
    PortfolioPositionSnapshot,
    PortfolioSnapshot,
    PriceSeriesPoint,
    ProductMetadataSnapshot,
    VolatilityState,
)


def _decimal(value: object | None, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    text = str(value).strip()
    if not text:
        return Decimal(default)
    return Decimal(text)


class CoinbaseIntxMarketDataProvider:
    OPEN_ORDER_STATUSES = {"open", "pending", "active"}

    def __init__(self) -> None:
        self.runtime_client = CoinbaseIntxRuntimeClient()

    def collect_market(self, coins: list[str]) -> dict[str, MarketSnapshotNormalized]:
        payload: dict[str, MarketSnapshotNormalized] = {}
        for coin in coins:
            snapshot = self.runtime_client.snapshot(coin)
            liquidity = self._liquidity_snapshot(coin)
            payload[coin] = MarketSnapshotNormalized(
                snapshot_id=f"{coin.lower()}-{int(snapshot['captured_at'].timestamp())}",
                coin=coin,
                product_id=snapshot["product_id"],
                mark_price=str(snapshot["mark_price"]),
                index_price=str(snapshot["index_price"]) if snapshot.get("index_price") is not None else None,
                funding_rate=str(snapshot["funding_rate"]) if snapshot["funding_rate"] is not None else None,
                premium=str(snapshot["premium"]) if snapshot.get("premium") is not None else None,
                open_interest=str(snapshot["open_interest"]) if snapshot["open_interest"] is not None else None,
                day_notional_volume=str(snapshot["day_notional_volume"]) if snapshot["day_notional_volume"] is not None else None,
                spread_bps=liquidity.spread_bps,
                trading_status=snapshot.get("trading_status"),
                trading_disabled=bool(snapshot.get("trading_disabled")),
                cancel_only=bool(snapshot.get("cancel_only")),
                limit_only=bool(snapshot.get("limit_only")),
                post_only=bool(snapshot.get("post_only")),
                captured_at=snapshot["captured_at"],
                raw=snapshot["raw"],
            )
        return payload

    def collect_accounts(self, coins: list[str]) -> dict[str, AccountSnapshot]:
        payload: dict[str, AccountSnapshot] = {}
        portfolio = self.runtime_client.portfolio()
        for coin in coins:
            account = self.runtime_client.account(coin)
            payload[coin] = AccountSnapshot(
                coin=coin,
                total_equity_usd=str(portfolio.get("total_equity_usd") or account["total_equity_usd"]),
                available_equity_usd=str(portfolio.get("available_equity_usd") or account["available_equity_usd"]),
                current_side=account["current_side"],
                current_notional_usd=account["current_notional_usd"],
                current_leverage=account["current_leverage"],
                current_quantity=account.get("current_quantity"),
                entry_price=account.get("entry_price"),
                unrealized_pnl_usd=account.get("unrealized_pnl_usd"),
                liquidation_price=account.get("liquidation_price"),
                raw=account["raw"],
            )
        return payload

    def collect_portfolio(self) -> PortfolioSnapshot:
        portfolio = self.runtime_client.portfolio()
        total_equity = _decimal(portfolio.get("total_equity_usd"))
        open_orders = self._list_open_orders()
        positions: list[PortfolioPositionSnapshot] = []
        for payload in portfolio.get("positions", []):
            notional = _decimal(payload.get("notional_usd"))
            share_pct = notional_to_pct_of_exposure_budget(
                notional_usd=notional,
                total_equity_usd=total_equity,
                max_leverage=self.runtime_client.settings.execution.max_leverage,
            )
            positions.append(
                PortfolioPositionSnapshot(
                    coin=str(payload.get("coin") or "").upper(),
                    side=str(payload.get("side") or "flat"),
                    quantity=str(payload.get("quantity") or "0"),
                    notional_usd=str(notional),
                    leverage=str(payload.get("leverage") or "0"),
                    entry_price=str(payload.get("entry_price") or "0"),
                    unrealized_pnl_usd=str(payload.get("unrealized_pnl_usd") or "0"),
                    position_share_pct_of_equity=round(share_pct, 4),
                    opened_at=payload.get("opened_at"),
                    raw=dict(payload.get("raw") or {}),
                )
            )
        return PortfolioSnapshot(
            starting_equity_usd=str(portfolio.get("starting_equity_usd") or "0"),
            realized_pnl_usd=str(portfolio.get("realized_pnl_usd") or "0"),
            unrealized_pnl_usd=str(portfolio.get("unrealized_pnl_usd") or "0"),
            total_equity_usd=str(portfolio.get("total_equity_usd") or "0"),
            available_equity_usd=str(portfolio.get("available_equity_usd") or "0"),
            total_exposure_usd=str(portfolio.get("total_exposure_usd") or "0"),
            open_order_hold_usd=str(sum((self._order_hold_usd(order) for order in open_orders), Decimal("0"))),
            positions=positions,
            raw={"source": "coinbase_intx", "portfolio": portfolio},
        )

    def collect_product_metadata(self, coins: list[str]) -> dict[str, ProductMetadataSnapshot]:
        payload: dict[str, ProductMetadataSnapshot] = {}
        for coin in coins:
            product = self.runtime_client.product(coin)
            snapshot = self.runtime_client.snapshot(coin)
            payload[coin] = ProductMetadataSnapshot(
                coin=coin,
                product_id=product.product_id,
                tick_size=str(product.quote_increment),
                size_increment=str(product.base_increment),
                min_size=str(product.base_min_size) if product.base_min_size is not None else None,
                min_notional=str(product.quote_min_size),
                max_leverage=str(snapshot["max_leverage"]) if snapshot.get("max_leverage") is not None else None,
                trading_status=product.status,
                trading_disabled=product.trading_disabled,
                cancel_only=product.cancel_only,
                limit_only=product.limit_only,
                post_only=product.post_only,
                raw=product.raw,
            )
        return payload

    def collect_market_context(self, coins: list[str]) -> dict[str, MarketContextNormalized]:
        contexts: dict[str, MarketContextNormalized] = {}
        for coin in coins:
            product_id = self.runtime_client.product_id(coin)
            series_payload = {
                "15m": self._fetch_series(product_id, granularity="FIFTEEN_MINUTE", lookback=24, interval_seconds=900),
                "1h": self._fetch_series(product_id, granularity="ONE_HOUR", lookback=24, interval_seconds=3600),
                "4h": self._fetch_series(product_id, granularity="FOUR_HOUR", lookback=24, interval_seconds=14400),
                "24h": self._fetch_series(product_id, granularity="ONE_DAY", lookback=30, interval_seconds=86400),
            }
            liquidity = self._liquidity_snapshot(coin)
            contexts[coin] = MarketContextNormalized(
                coin=coin,
                product_id=product_id,
                compressed_price_series=series_payload,
                key_levels=self._key_levels(series_payload),
                breakout_retest_state=self._breakout_state(series_payload),
                volatility_state=self._volatility_state(series_payload.get("15m")),
                shape_summary=self._shape_summary(series_payload),
                liquidity=liquidity,
                raw={"source": "coinbase_intx"},
            )
        return contexts

    def collect_execution_history(self, coins: list[str]) -> dict[str, ExecutionHistorySnapshot]:
        payload: dict[str, ExecutionHistorySnapshot] = {}
        for coin in coins:
            product_id = self.runtime_client.product_id(coin)
            orders = self.runtime_client.client.list_orders(product_id=product_id, limit=50)
            fills = self.runtime_client.client.list_fills(product_id=product_id)[:20]
            failures = [
                order
                for order in orders
                if str(order.get("status") or "").lower() in {"failed", "rejected", "cancelled"}
                or bool(order.get("error_response"))
            ]
            open_orders = [self._build_open_order_snapshot(order) for order in orders if self._is_open_order(order)]
            payload[coin] = ExecutionHistorySnapshot(
                coin=coin,
                product_id=product_id,
                recent_orders=orders[:20],
                recent_fills=fills,
                failure_sources=failures,
                open_orders=open_orders,
                raw={"source": "coinbase_intx"},
            )
        return payload

    def _fetch_series(
        self,
        product_id: str,
        *,
        granularity: str,
        lookback: int,
        interval_seconds: int,
    ) -> CompressedPriceSeries:
        end = datetime.now(UTC)
        start = end - timedelta(seconds=lookback * interval_seconds)
        candles = self.runtime_client.client.get_public_candles(
            product_id,
            start=int(start.timestamp()),
            end=int(end.timestamp()),
            granularity=granularity,
            limit=lookback,
        )
        points = [PriceSeriesPoint(timestamp=candle.start, close=str(candle.close)) for candle in candles[-lookback:]]
        change_pct = None
        if len(candles) >= 2:
            first = Decimal(str(candles[0].close))
            last = Decimal(str(candles[-1].close))
            if first != 0:
                change_pct = round(float((last - first) / first * Decimal("100")), 4)
        return CompressedPriceSeries(
            window=self._window_name(granularity),
            granularity=granularity,
            points=points,
            change_pct=change_pct,
        )

    def _liquidity_snapshot(self, coin: str) -> LiquiditySnapshot:
        product_raw = self.runtime_client.product(coin).raw
        best_bid = _decimal(product_raw.get("best_bid")) if product_raw.get("best_bid") is not None else None
        best_ask = _decimal(product_raw.get("best_ask")) if product_raw.get("best_ask") is not None else None
        spread_bps = None
        if best_bid is not None and best_ask is not None and best_bid > 0 and best_ask >= best_bid:
            mid = (best_bid + best_ask) / Decimal("2")
            if mid > 0:
                spread_bps = round(float((best_ask - best_bid) / mid * Decimal("10000")), 4)
        return LiquiditySnapshot(
            best_bid=str(best_bid) if best_bid is not None else None,
            best_ask=str(best_ask) if best_ask is not None else None,
            spread_bps=spread_bps,
            orderbook_depth=OrderbookDepthSnapshot(
                best_bid_size=str(product_raw.get("best_bid_size")) if product_raw.get("best_bid_size") is not None else None,
                best_ask_size=str(product_raw.get("best_ask_size")) if product_raw.get("best_ask_size") is not None else None,
                bid_depth_notional_usd=str(product_raw.get("bid_depth")) if product_raw.get("bid_depth") is not None else None,
                ask_depth_notional_usd=str(product_raw.get("ask_depth")) if product_raw.get("ask_depth") is not None else None,
                raw={
                    key: product_raw.get(key)
                    for key in ("best_bid_size", "best_ask_size", "bid_depth", "ask_depth")
                    if product_raw.get(key) is not None
                },
            ),
        )

    def _key_levels(self, series_payload: dict[str, CompressedPriceSeries]) -> list[KeyLevel]:
        levels: list[KeyLevel] = []
        for label in ("15m", "1h", "4h", "24h"):
            series = series_payload.get(label)
            prices = self._prices_from_series(series)
            if not prices:
                continue
            levels.append(KeyLevel(label=f"{label}_high", price=str(max(prices)), source=label))
            levels.append(KeyLevel(label=f"{label}_low", price=str(min(prices)), source=label))
        return levels

    def _breakout_state(self, series_payload: dict[str, CompressedPriceSeries]) -> BreakoutRetestState:
        hourly = series_payload.get("1h")
        prices = self._prices_from_series(hourly)
        if len(prices) < 3:
            return BreakoutRetestState()
        current = prices[-1]
        prior_high = max(prices[:-1])
        prior_low = min(prices[:-1])
        if current > prior_high:
            return BreakoutRetestState(state="up_breakout", reference_level="1h_high", reference_price=str(prior_high))
        if current < prior_low:
            return BreakoutRetestState(state="down_breakout", reference_level="1h_low", reference_price=str(prior_low))
        return BreakoutRetestState(state="range", reference_level="1h_range", reference_price=str(current))

    def _volatility_state(self, series: CompressedPriceSeries | None) -> VolatilityState:
        prices = self._prices_from_series(series)
        if len(prices) < 10:
            return VolatilityState()
        returns = []
        for idx in range(1, len(prices)):
            previous = prices[idx - 1]
            current = prices[idx]
            if previous == 0:
                returns.append(0.0)
            else:
                returns.append(float((current - previous) / previous))
        short = returns[-8:]
        long = returns[-24:] if len(returns) >= 24 else returns
        short_vol = pstdev(short) if len(short) >= 2 else 0.0
        long_vol = pstdev(long) if len(long) >= 2 else 0.0
        state = "normal"
        if long_vol > 0 and short_vol > long_vol * 1.2:
            state = "expanding"
        elif long_vol > 0 and short_vol < long_vol * 0.8:
            state = "contracting"
        return VolatilityState(
            state=state,
            short_window_realized_vol=round(short_vol, 6),
            long_window_realized_vol=round(long_vol, 6),
        )

    def _shape_summary(self, series_payload: dict[str, CompressedPriceSeries]) -> str:
        hourly_prices = self._prices_from_series(series_payload.get("1h"))
        if len(hourly_prices) < 2:
            return "insufficient_price_shape"
        direction = "uptrend" if hourly_prices[-1] > hourly_prices[0] else "downtrend"
        volatility = self._volatility_state(series_payload.get("15m")).state
        breakout = self._breakout_state(series_payload).state
        average = mean(hourly_prices)
        location = "above_mean" if hourly_prices[-1] >= average else "below_mean"
        return f"{direction}|{breakout}|{volatility}|{location}"

    def _list_open_orders(self) -> list[dict]:
        orders: list[dict] = []
        for coin in self.runtime_client.settings.execution.supported_coins:
            product_id = self.runtime_client.product_id(coin)
            orders.extend(
                order
                for order in self.runtime_client.client.list_orders(product_id=product_id, limit=50)
                if self._is_open_order(order)
            )
        return orders

    def _build_open_order_snapshot(self, order: dict) -> OpenOrderSnapshot:
        return OpenOrderSnapshot(
            order_id=str(order.get("order_id") or order.get("client_order_id") or ""),
            status=order.get("status"),
            side=order.get("side"),
            order_type=order.get("order_type"),
            notional_usd=str(self._order_hold_usd(order)) if self._order_hold_usd(order) > 0 else None,
            limit_price=str(order.get("limit_price")) if order.get("limit_price") is not None else None,
            base_size=str(order.get("base_size")) if order.get("base_size") is not None else None,
            created_at=str(order.get("created_time") or order.get("created_at")) if order.get("created_time") or order.get("created_at") else None,
            raw=order,
        )

    def _is_open_order(self, order: dict) -> bool:
        return str(order.get("status") or "").lower() in self.OPEN_ORDER_STATUSES

    def _order_hold_usd(self, order: dict) -> Decimal:
        return _decimal(
            order.get("outstanding_hold_amount")
            or order.get("quote_size")
            or order.get("total_value_after_fees")
            or order.get("filled_value"),
            default="0",
        )

    @staticmethod
    def _prices_from_series(series: CompressedPriceSeries | None) -> list[Decimal]:
        if series is None:
            return []
        return [Decimal(point.close) for point in series.points]

    @staticmethod
    def _window_name(granularity: str) -> str:
        return {
            "FIFTEEN_MINUTE": "15m",
            "ONE_HOUR": "1h",
            "FOUR_HOUR": "4h",
            "ONE_DAY": "24h",
        }.get(granularity, granularity.lower())
