from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from urllib import request
from urllib.error import HTTPError, URLError

from ..config import PerpConfig
from ..models import Candle, PerpPaperAccount, PerpPaperOrderResult, PerpPaperPortfolio, PerpPaperPosition, PerpSnapshot
from ..state import StateStore


def _d(value: object | None, default: str = "0") -> Decimal:
    if value is None:
        return Decimal(default)
    return Decimal(str(value))


class HyperliquidPublicClient:
    def __init__(self, api_base: str = "https://api.hyperliquid.xyz") -> None:
        self.api_base = api_base.rstrip("/")

    def _post_info(self, payload: dict[str, object]) -> object:
        last_error: Exception | None = None
        for attempt in range(3):
            req = request.Request(
                f"{self.api_base}/info",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            try:
                with request.urlopen(req, timeout=20) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise
            except URLError as exc:
                last_error = exc
                if attempt == 2:
                    raise
            time.sleep(2**attempt)
        if last_error is not None:
            raise last_error
        raise RuntimeError("hyperliquid public info request failed without error")

    def snapshot(self, coin: str = "BTC") -> PerpSnapshot:
        meta, asset_ctxs = self._post_info({"type": "metaAndAssetCtxs"})
        coin = coin.upper()
        for idx, asset in enumerate(meta["universe"]):
            if asset["name"] != coin:
                continue
            ctx = asset_ctxs[idx]
            return PerpSnapshot(
                exchange="hyperliquid",
                coin=coin,
                mark_price=_d(ctx.get("markPx")),
                oracle_price=_d(ctx.get("oraclePx")),
                mid_price=_d(ctx.get("midPx")) if ctx.get("midPx") is not None else None,
                funding_rate=_d(ctx.get("funding")) if ctx.get("funding") is not None else None,
                premium=_d(ctx.get("premium")) if ctx.get("premium") is not None else None,
                open_interest=_d(ctx.get("openInterest")) if ctx.get("openInterest") is not None else None,
                max_leverage=_d(asset.get("maxLeverage")) if asset.get("maxLeverage") is not None else None,
                day_notional_volume=_d(ctx.get("dayNtlVlm")) if ctx.get("dayNtlVlm") is not None else None,
                raw={"asset": asset, "ctx": ctx},
            )
        raise ValueError(f"Hyperliquid coin not found: {coin}")

    def candles(self, coin: str = "BTC", interval: str = "15m", lookback: int = 48) -> list[Candle]:
        end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        interval_ms_map = {
            "1m": 60_000,
            "3m": 180_000,
            "5m": 300_000,
            "15m": 900_000,
            "30m": 1_800_000,
            "1h": 3_600_000,
            "4h": 14_400_000,
        }
        interval_ms = interval_ms_map.get(interval, 900_000)
        start_ms = end_ms - (lookback * interval_ms)
        rows = self._post_info(
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": coin.upper(),
                    "interval": interval,
                    "startTime": start_ms,
                    "endTime": end_ms,
                },
            }
        )
        candles: list[Candle] = []
        for row in rows:
            candles.append(
                Candle(
                    start=int(row.get("t", 0)),
                    low=_d(row.get("l")),
                    high=_d(row.get("h")),
                    open=_d(row.get("o")),
                    close=_d(row.get("c")),
                    volume=_d(row.get("v")),
                )
            )
        candles.sort(key=lambda item: item.start)
        return candles


@dataclass
class HyperliquidPaperContext:
    config: PerpConfig
    client: HyperliquidPublicClient
    state: StateStore


class HyperliquidPaperEngine:
    def __init__(self, ctx: HyperliquidPaperContext) -> None:
        self.ctx = ctx

    def _coin(self, coin: str | None = None) -> str:
        return (coin or self.ctx.config.coin).upper()

    def _coins(self) -> list[str]:
        coins = [coin.upper() for coin in (self.ctx.config.coins or [self.ctx.config.coin])]
        return list(dict.fromkeys(coins))

    def _realized_key(self) -> str:
        return f"perp:{self.ctx.config.exchange}:portfolio:realized_pnl_usd"

    def snapshot(self, coin: str | None = None) -> PerpSnapshot:
        return self.ctx.client.snapshot(self._coin(coin))

    def candles(self, coin: str | None = None, interval: str = "15m", lookback: int = 48) -> list[Candle]:
        return self.ctx.client.candles(self._coin(coin), interval=interval, lookback=lookback)

    def position(self, coin: str | None = None) -> PerpPaperPosition | None:
        coin = self._coin(coin)
        payload = self.ctx.state.get_perp_paper_position(self.ctx.config.exchange, coin)
        if not payload:
            return None
        return PerpPaperPosition.model_validate(payload)

    def list_positions(self) -> list[PerpPaperPosition]:
        positions: list[PerpPaperPosition] = []
        for coin in self._coins():
            position = self.position(coin)
            if position is not None:
                positions.append(position)
        return positions

    def _unrealized_pnl(self, position: PerpPaperPosition, mark_price: Decimal) -> Decimal:
        if position.side == "long":
            return ((mark_price - position.entry_price) / position.entry_price) * position.notional_usd
        return ((position.entry_price - mark_price) / position.entry_price) * position.notional_usd

    def portfolio(self) -> PerpPaperPortfolio:
        starting = Decimal(str(self.ctx.config.paper_starting_equity_usd))
        realized = _d(self.ctx.state.get_value(self._realized_key()), "0")
        positions = self.list_positions()
        unrealized = Decimal("0")
        margin_used = Decimal("0")
        total_exposure = Decimal("0")
        for position in positions:
            snapshot = self.snapshot(position.coin)
            unrealized += self._unrealized_pnl(position, snapshot.mark_price)
            margin_used += position.margin_used_usd
            total_exposure += position.notional_usd
        total = starting + realized + unrealized
        available = total - margin_used
        return PerpPaperPortfolio(
            exchange=self.ctx.config.exchange,
            starting_equity_usd=starting,
            realized_pnl_usd=realized,
            unrealized_pnl_usd=unrealized,
            total_equity_usd=total,
            available_equity_usd=available,
            total_exposure_usd=total_exposure,
            positions=positions,
        )

    def account(self, coin: str | None = None) -> PerpPaperAccount:
        coin = self._coin(coin)
        portfolio = self.portfolio()
        position = self.position(coin)
        unrealized = Decimal("0")
        mark_price = None
        if position is not None:
            snapshot = self.snapshot(coin)
            mark_price = snapshot.mark_price
            unrealized = self._unrealized_pnl(position, mark_price)
        return PerpPaperAccount(
            exchange=self.ctx.config.exchange,
            coin=coin,
            starting_equity_usd=portfolio.starting_equity_usd,
            realized_pnl_usd=portfolio.realized_pnl_usd,
            unrealized_pnl_usd=unrealized,
            total_equity_usd=portfolio.total_equity_usd,
            available_equity_usd=portfolio.available_equity_usd,
            position=position,
            mark_price=mark_price,
        )

    def minimum_trade_notional_usd(self, coin: str | None = None) -> Decimal:
        return Decimal("0")

    def _effective_leverage(self, leverage: Decimal | None, snapshot: PerpSnapshot) -> Decimal | None:
        effective = leverage or Decimal(str(self.ctx.config.max_leverage))
        if effective > Decimal(str(self.ctx.config.max_leverage)):
            return None
        if effective > (snapshot.max_leverage or Decimal("1")):
            return None
        return effective

    def _limit_payload(self, portfolio: PerpPaperPortfolio) -> tuple[Decimal, Decimal, Decimal]:
        max_total_exposure = portfolio.total_equity_usd * Decimal(str(self.ctx.config.max_total_exposure_pct_of_equity / 100))
        max_order = max_total_exposure * Decimal(str(self.ctx.config.max_order_share_pct_of_exposure_budget / 100))
        max_position = max_total_exposure * Decimal(str(self.ctx.config.max_position_share_pct_of_exposure_budget / 100))
        return max_total_exposure, max_order, max_position

    def _store_position(self, position: PerpPaperPosition) -> None:
        payload = position.model_dump(mode="json")
        self.ctx.state.upsert_perp_paper_position(
            exchange=self.ctx.config.exchange,
            coin=position.coin,
            side=position.side,
            notional_usd=str(position.notional_usd),
            leverage=str(position.leverage),
            entry_price=str(position.entry_price),
            quantity=str(position.quantity),
            margin_used_usd=str(position.margin_used_usd),
            opened_at=position.opened_at.isoformat(),
            payload=payload,
        )

    def open_paper(
        self,
        *,
        side: Literal["long", "short"],
        notional_usd: Decimal,
        leverage: Decimal | None = None,
        coin: str | None = None,
    ) -> PerpPaperOrderResult:
        coin = self._coin(coin)
        if self.ctx.config.mode.value != "paper":
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action="open",
                side=side,
                notional_usd=notional_usd,
                leverage=leverage,
                message="perp_mode_is_not_paper",
            )
        if self.position(coin) is not None:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action="open",
                side=side,
                notional_usd=notional_usd,
                leverage=leverage,
                message="paper_position_already_open",
            )

        snapshot = self.snapshot(coin)
        portfolio = self.portfolio()
        effective_leverage = self._effective_leverage(leverage, snapshot)
        if effective_leverage is None:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action="open",
                side=side,
                notional_usd=notional_usd,
                leverage=leverage,
                message="leverage_above_limit",
            )

        max_total_exposure, max_order, max_position = self._limit_payload(portfolio)
        if notional_usd > max_order:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action="open",
                side=side,
                notional_usd=notional_usd,
                leverage=effective_leverage,
                message="notional_above_order_limit",
                raw={"max_order_notional_usd": str(max_order)},
            )
        if notional_usd > max_position:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action="open",
                side=side,
                notional_usd=notional_usd,
                leverage=effective_leverage,
                message="notional_above_position_limit",
                raw={"max_position_notional_usd": str(max_position)},
            )
        if portfolio.total_exposure_usd + notional_usd > max_total_exposure:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action="open",
                side=side,
                notional_usd=notional_usd,
                leverage=effective_leverage,
                message="total_exposure_above_limit",
                raw={"max_total_exposure_notional_usd": str(max_total_exposure)},
            )

        margin_used = notional_usd / effective_leverage
        if margin_used > portfolio.available_equity_usd:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action="open",
                side=side,
                notional_usd=notional_usd,
                leverage=effective_leverage,
                message="insufficient_paper_equity",
                raw={"available_equity_usd": str(portfolio.available_equity_usd)},
            )

        quantity = notional_usd / snapshot.mark_price
        opened_at = datetime.now(timezone.utc).isoformat()
        position = PerpPaperPosition(
            exchange=self.ctx.config.exchange,
            coin=coin,
            side=side,
            notional_usd=notional_usd,
            leverage=effective_leverage,
            entry_price=snapshot.mark_price,
            quantity=quantity,
            margin_used_usd=margin_used,
            opened_at=datetime.fromisoformat(opened_at),
            raw={"funding_rate": str(snapshot.funding_rate) if snapshot.funding_rate is not None else None},
        )
        payload = position.model_dump(mode="json")
        self._store_position(position)
        self.ctx.state.record_perp_paper_fill(
            exchange=self.ctx.config.exchange,
            coin=coin,
            action="open",
            side=side,
            notional_usd=str(notional_usd),
            leverage=str(effective_leverage),
            price=str(snapshot.mark_price),
            realized_pnl_usd=None,
            payload=payload,
        )
        return PerpPaperOrderResult(
            success=True,
            exchange=self.ctx.config.exchange,
            coin=coin,
            action="open",
            side=side,
            notional_usd=notional_usd,
            leverage=effective_leverage,
            price=snapshot.mark_price,
            message="paper_perp_position_opened",
            raw=payload,
        )

    def add_paper(
        self,
        *,
        side: Literal["long", "short"],
        notional_usd: Decimal,
        leverage: Decimal | None = None,
        coin: str | None = None,
    ) -> PerpPaperOrderResult:
        coin = self._coin(coin)
        if self.ctx.config.mode.value != "paper":
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action="add",
                side=side,
                notional_usd=notional_usd,
                leverage=leverage,
                message="perp_mode_is_not_paper",
            )
        position = self.position(coin)
        if position is None:
            return self.open_paper(side=side, notional_usd=notional_usd, leverage=leverage, coin=coin)
        if position.side != side:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action="add",
                side=side,
                notional_usd=notional_usd,
                leverage=leverage,
                message="paper_position_side_conflict",
            )

        snapshot = self.snapshot(coin)
        portfolio = self.portfolio()
        effective_leverage = self._effective_leverage(leverage, snapshot)
        if effective_leverage is None:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action="add",
                side=side,
                notional_usd=notional_usd,
                leverage=leverage,
                message="leverage_above_limit",
            )

        max_total_exposure, max_order, max_position = self._limit_payload(portfolio)
        if notional_usd > max_order:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action="add",
                side=side,
                notional_usd=notional_usd,
                leverage=effective_leverage,
                message="notional_above_order_limit",
                raw={"max_order_notional_usd": str(max_order)},
            )
        if position.notional_usd + notional_usd > max_position:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action="add",
                side=side,
                notional_usd=notional_usd,
                leverage=effective_leverage,
                message="notional_above_position_limit",
                raw={"max_position_notional_usd": str(max_position)},
            )
        if portfolio.total_exposure_usd + notional_usd > max_total_exposure:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action="add",
                side=side,
                notional_usd=notional_usd,
                leverage=effective_leverage,
                message="total_exposure_above_limit",
                raw={"max_total_exposure_notional_usd": str(max_total_exposure)},
            )

        margin_delta = notional_usd / effective_leverage
        if margin_delta > portfolio.available_equity_usd:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action="add",
                side=side,
                notional_usd=notional_usd,
                leverage=effective_leverage,
                message="insufficient_paper_equity",
                raw={"available_equity_usd": str(portfolio.available_equity_usd)},
            )

        added_quantity = notional_usd / snapshot.mark_price
        total_quantity = position.quantity + added_quantity
        total_notional = position.notional_usd + notional_usd
        total_margin = position.margin_used_usd + margin_delta
        weighted_entry = (
            ((position.entry_price * position.quantity) + (snapshot.mark_price * added_quantity)) / total_quantity
            if total_quantity > 0
            else snapshot.mark_price
        )
        updated = PerpPaperPosition(
            exchange=self.ctx.config.exchange,
            coin=coin,
            side=side,
            notional_usd=total_notional,
            leverage=(total_notional / total_margin) if total_margin > 0 else effective_leverage,
            entry_price=weighted_entry,
            quantity=total_quantity,
            margin_used_usd=total_margin,
            opened_at=position.opened_at,
            raw={"funding_rate": str(snapshot.funding_rate) if snapshot.funding_rate is not None else None},
        )
        payload = updated.model_dump(mode="json")
        self._store_position(updated)
        self.ctx.state.record_perp_paper_fill(
            exchange=self.ctx.config.exchange,
            coin=coin,
            action="add",
            side=side,
            notional_usd=str(notional_usd),
            leverage=str(updated.leverage),
            price=str(snapshot.mark_price),
            realized_pnl_usd=None,
            payload=payload,
        )
        return PerpPaperOrderResult(
            success=True,
            exchange=self.ctx.config.exchange,
            coin=coin,
            action="add",
            side=side,
            notional_usd=notional_usd,
            leverage=updated.leverage,
            price=snapshot.mark_price,
            message="paper_perp_position_increased",
            raw=payload,
        )

    def reduce_paper(self, *, notional_usd: Decimal, coin: str | None = None) -> PerpPaperOrderResult:
        coin = self._coin(coin)
        position = self.position(coin)
        if position is None:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action="reduce",
                message="no_open_paper_position",
            )
        if notional_usd <= 0:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action="reduce",
                side=position.side,
                notional_usd=notional_usd,
                leverage=position.leverage,
                message="invalid_reduce_notional",
            )
        if notional_usd >= position.notional_usd:
            return self.close_paper(coin)

        snapshot = self.snapshot(coin)
        realized = self._unrealized_pnl(position, snapshot.mark_price) * (notional_usd / position.notional_usd)
        prior = _d(self.ctx.state.get_value(self._realized_key()), "0")
        self.ctx.state.set_value(self._realized_key(), str(prior + realized))
        remaining_ratio = (position.notional_usd - notional_usd) / position.notional_usd
        updated = PerpPaperPosition(
            exchange=self.ctx.config.exchange,
            coin=coin,
            side=position.side,
            notional_usd=position.notional_usd - notional_usd,
            leverage=position.leverage,
            entry_price=position.entry_price,
            quantity=position.quantity * remaining_ratio,
            margin_used_usd=position.margin_used_usd * remaining_ratio,
            opened_at=position.opened_at,
            raw=position.raw,
        )
        payload = {
            "entry_price": str(position.entry_price),
            "exit_price": str(snapshot.mark_price),
            "notional_usd": str(notional_usd),
            "remaining_notional_usd": str(updated.notional_usd),
            "leverage": str(position.leverage),
            "realized_pnl_usd": str(realized),
            "side": position.side,
        }
        self._store_position(updated)
        self.ctx.state.record_perp_paper_fill(
            exchange=self.ctx.config.exchange,
            coin=coin,
            action="reduce",
            side=position.side,
            notional_usd=str(notional_usd),
            leverage=str(position.leverage),
            price=str(snapshot.mark_price),
            realized_pnl_usd=str(realized),
            payload=payload,
        )
        return PerpPaperOrderResult(
            success=True,
            exchange=self.ctx.config.exchange,
            coin=coin,
            action="reduce",
            side=position.side,
            notional_usd=notional_usd,
            leverage=position.leverage,
            price=snapshot.mark_price,
            realized_pnl_usd=realized,
            message="paper_perp_position_reduced",
            raw=payload,
        )

    def close_paper(self, coin: str | None = None) -> PerpPaperOrderResult:
        coin = self._coin(coin)
        position = self.position(coin)
        if position is None:
            return PerpPaperOrderResult(
                success=False,
                exchange=self.ctx.config.exchange,
                coin=coin,
                action="close",
                message="no_open_paper_position",
            )
        snapshot = self.snapshot(coin)
        realized = self._unrealized_pnl(position, snapshot.mark_price)
        prior = _d(self.ctx.state.get_value(self._realized_key()), "0")
        self.ctx.state.set_value(self._realized_key(), str(prior + realized))
        self.ctx.state.clear_perp_paper_position(self.ctx.config.exchange, coin)
        payload = {
            "entry_price": str(position.entry_price),
            "exit_price": str(snapshot.mark_price),
            "notional_usd": str(position.notional_usd),
            "leverage": str(position.leverage),
            "realized_pnl_usd": str(realized),
            "side": position.side,
        }
        self.ctx.state.record_perp_paper_fill(
            exchange=self.ctx.config.exchange,
            coin=coin,
            action="close",
            side=position.side,
            notional_usd=str(position.notional_usd),
            leverage=str(position.leverage),
            price=str(snapshot.mark_price),
            realized_pnl_usd=str(realized),
            payload=payload,
        )
        return PerpPaperOrderResult(
            success=True,
            exchange=self.ctx.config.exchange,
            coin=coin,
            action="close",
            side=position.side,
            notional_usd=position.notional_usd,
            leverage=position.leverage,
            price=snapshot.mark_price,
            realized_pnl_usd=realized,
            message="paper_perp_position_closed",
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
        coin = self._coin(coin)
        return PerpPaperOrderResult(
            success=False,
            exchange=self.ctx.config.exchange,
            coin=coin,
            action="open_live",
            side=side,
            notional_usd=notional_usd,
            leverage=leverage,
            message="hyperliquid_live_not_configured",
        )
