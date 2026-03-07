from __future__ import annotations

from decimal import Decimal
from typing import Literal, Protocol

from ..models import Candle, PerpPaperAccount, PerpPaperOrderResult, PerpPaperPortfolio, PerpPaperPosition, PerpSnapshot


class PerpEngine(Protocol):
    def snapshot(self, coin: str | None = None) -> PerpSnapshot: ...

    def candles(self, coin: str | None = None, interval: str = "15m", lookback: int = 48) -> list[Candle]: ...

    def position(self, coin: str | None = None) -> PerpPaperPosition | None: ...

    def list_positions(self) -> list[PerpPaperPosition]: ...

    def portfolio(self) -> PerpPaperPortfolio: ...

    def account(self, coin: str | None = None) -> PerpPaperAccount: ...

    def open_paper(
        self,
        *,
        side: Literal["long", "short"],
        notional_usd: Decimal,
        leverage: Decimal | None = None,
        coin: str | None = None,
    ) -> PerpPaperOrderResult: ...

    def add_paper(
        self,
        *,
        side: Literal["long", "short"],
        notional_usd: Decimal,
        leverage: Decimal | None = None,
        coin: str | None = None,
    ) -> PerpPaperOrderResult: ...

    def reduce_paper(self, *, notional_usd: Decimal, coin: str | None = None) -> PerpPaperOrderResult: ...

    def close_paper(self, coin: str | None = None) -> PerpPaperOrderResult: ...

    def open_live(
        self,
        *,
        side: Literal["long", "short"],
        notional_usd: Decimal,
        leverage: Decimal | None = None,
        coin: str | None = None,
    ) -> PerpPaperOrderResult: ...

    def minimum_trade_notional_usd(self, coin: str | None = None) -> Decimal: ...
