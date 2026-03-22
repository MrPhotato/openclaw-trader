from __future__ import annotations

from ...protocols.market_types import Candle


class CoinbasePublicMarketMixin:
    def get_candles(self, product_id: str, *, start: int, end: int, granularity: str, limit: int | None = None) -> list[Candle]:
        params: dict[str, object] = {
            "start": str(start),
            "end": str(end),
            "granularity": granularity,
        }
        if limit is not None:
            params["limit"] = limit
        payload = self._request("GET", f"/api/v3/brokerage/products/{product_id}/candles", params=params)
        candles = [Candle(**candle) for candle in payload.get("candles", [])]
        return sorted(candles, key=lambda candle: candle.start)

    def get_public_candles(self, product_id: str, *, start: int, end: int, granularity: str, limit: int | None = None) -> list[Candle]:
        params: dict[str, object] = {
            "start": str(start),
            "end": str(end),
            "granularity": granularity,
        }
        if limit is not None:
            params["limit"] = limit
        payload = self._request(
            "GET",
            f"/api/v3/brokerage/market/products/{product_id}/candles",
            params=params,
            max_retries=max(self.max_retries, self.PUBLIC_DATA_MIN_RETRIES),
        )
        candles = [Candle(**candle) for candle in payload.get("candles", [])]
        return sorted(candles, key=lambda candle: candle.start)
