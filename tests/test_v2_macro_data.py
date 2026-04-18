from __future__ import annotations

import unittest
from datetime import UTC, datetime

from openclaw_trader.modules.trade_gateway.macro_data import (
    MacroDataService,
    MacroSnapshot,
)
from openclaw_trader.modules.trade_gateway.macro_data.models import (
    EtfActivity,
    FearGreedIndex,
    MacroPrice,
)
from openclaw_trader.modules.trade_gateway.macro_data.service import (
    DEFAULT_MACRO_SYMBOLS,
    MacroDataConfig,
)


class StubPriceProvider:
    def __init__(
        self,
        *,
        quotes: dict[str, MacroPrice] | None = None,
        etfs: dict[str, EtfActivity] | None = None,
        quote_error: str | None = None,
        etf_error: str | None = None,
    ) -> None:
        self._quotes = dict(quotes or {})
        self._etfs = dict(etfs or {})
        self._quote_error = quote_error
        self._etf_error = etf_error
        self.quote_calls: list[str] = []
        self.etf_calls: list[str] = []

    def fetch_quote(self, yahoo_symbol: str) -> MacroPrice:
        self.quote_calls.append(yahoo_symbol)
        if self._quote_error is not None:
            return MacroPrice(symbol=yahoo_symbol, error=self._quote_error)
        return self._quotes.get(
            yahoo_symbol,
            MacroPrice(
                symbol=yahoo_symbol,
                price=42.0,
                as_of_utc=datetime(2026, 4, 18, tzinfo=UTC),
                is_market_open=False,
                staleness_seconds=3600,
            ),
        )

    def fetch_etf_activity(self, ticker: str) -> EtfActivity:
        self.etf_calls.append(ticker)
        if self._etf_error is not None:
            return EtfActivity(ticker=ticker, error=self._etf_error)
        return self._etfs.get(
            ticker,
            EtfActivity(
                ticker=ticker,
                close=40.0,
                volume=1_000_000,
                avg_volume_20d=800_000.0,
                as_of_utc=datetime(2026, 4, 18, tzinfo=UTC),
            ),
        )


class StubSentimentProvider:
    def __init__(
        self,
        *,
        value: int = 26,
        classification: str = "Fear",
        error: str | None = None,
    ) -> None:
        self._value = value
        self._classification = classification
        self._error = error
        self.calls = 0

    def fetch_btc_fear_greed(self) -> FearGreedIndex:
        self.calls += 1
        if self._error is not None:
            return FearGreedIndex(error=self._error)
        return FearGreedIndex(
            value=self._value,
            classification=self._classification,
            as_of_utc=datetime(2026, 4, 18, tzinfo=UTC),
        )


def _build_service(
    *,
    price: StubPriceProvider | None = None,
    sentiment: StubSentimentProvider | None = None,
    enabled: bool = True,
    refresh_interval: int = 900,
) -> MacroDataService:
    return MacroDataService(
        price_provider=price,
        sentiment_provider=sentiment,
        config=MacroDataConfig(
            enabled=enabled,
            refresh_interval_seconds=refresh_interval,
            etf_tickers=("IBIT", "FBTC"),
        ),
    )


class MacroDataServiceTests(unittest.TestCase):
    def test_collect_snapshot_returns_none_when_disabled(self):
        svc = _build_service(
            price=StubPriceProvider(),
            sentiment=StubSentimentProvider(),
            enabled=False,
        )
        self.assertIsNone(svc.collect_snapshot(force_refresh=True))

    def test_collect_snapshot_populates_all_fields_on_happy_path(self):
        price = StubPriceProvider()
        sentiment = StubSentimentProvider()
        svc = _build_service(price=price, sentiment=sentiment)

        snap = svc.collect_snapshot(force_refresh=True)

        self.assertIsInstance(snap, MacroSnapshot)
        self.assertEqual(snap.brent.price, 42.0)
        self.assertEqual(snap.wti.price, 42.0)
        self.assertEqual(snap.dxy.price, 42.0)
        self.assertEqual(snap.us10y_yield_pct.price, 42.0)
        self.assertEqual(snap.btc_fear_greed.value, 26)
        self.assertEqual(snap.btc_fear_greed.classification, "Fear")
        self.assertEqual(set(snap.btc_etf_activity.keys()), {"IBIT", "FBTC"})
        self.assertEqual(snap.fetch_errors, [])
        self.assertEqual(
            price.quote_calls,
            [DEFAULT_MACRO_SYMBOLS[k] for k in ("brent", "wti", "dxy", "us10y_yield_pct")],
        )
        self.assertEqual(price.etf_calls, ["IBIT", "FBTC"])
        self.assertEqual(sentiment.calls, 1)

    def test_collect_snapshot_uses_cache_within_refresh_interval(self):
        price = StubPriceProvider()
        sentiment = StubSentimentProvider()
        svc = _build_service(price=price, sentiment=sentiment, refresh_interval=3600)

        first = svc.collect_snapshot()
        second = svc.collect_snapshot()

        self.assertIs(first, second)
        # One round of fetches (4 quotes + 2 etfs + 1 fng)
        self.assertEqual(len(price.quote_calls), 4)
        self.assertEqual(len(price.etf_calls), 2)
        self.assertEqual(sentiment.calls, 1)

    def test_force_refresh_bypasses_cache(self):
        price = StubPriceProvider()
        sentiment = StubSentimentProvider()
        svc = _build_service(price=price, sentiment=sentiment, refresh_interval=3600)

        svc.collect_snapshot()
        svc.collect_snapshot(force_refresh=True)

        self.assertEqual(len(price.quote_calls), 8)
        self.assertEqual(sentiment.calls, 2)

    def test_provider_errors_are_accumulated_without_raising(self):
        price = StubPriceProvider(quote_error="yfinance_fetch_failed:boom", etf_error="yfinance_empty_series")
        sentiment = StubSentimentProvider(error="alternative_me_fetch_failed:timeout")
        svc = _build_service(price=price, sentiment=sentiment)

        snap = svc.collect_snapshot(force_refresh=True)

        self.assertIsNotNone(snap)
        self.assertIsNone(snap.brent.price)
        self.assertIsNone(snap.btc_fear_greed.value)
        self.assertEqual(len(snap.fetch_errors), 4 + 2 + 1)
        self.assertTrue(
            any("brent:" in err for err in snap.fetch_errors),
            msg=f"brent error missing: {snap.fetch_errors}",
        )
        self.assertTrue(
            any("etf:IBIT:" in err for err in snap.fetch_errors),
            msg=f"etf error missing: {snap.fetch_errors}",
        )
        self.assertTrue(any(err.startswith("fear_greed:") for err in snap.fetch_errors))

    def test_missing_sentiment_provider_is_treated_as_disabled(self):
        svc = _build_service(price=StubPriceProvider(), sentiment=None)
        snap = svc.collect_snapshot(force_refresh=True)
        self.assertIsNotNone(snap)
        self.assertEqual(snap.btc_fear_greed.error, "provider_disabled")
        self.assertIn("fear_greed:provider_disabled", snap.fetch_errors)


if __name__ == "__main__":
    unittest.main()
