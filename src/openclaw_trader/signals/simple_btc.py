from __future__ import annotations

from decimal import Decimal

from ..models import MarketSnapshot, RiskProfile, SignalDecision, SignalSide


def generate_btc_trend_signal(snapshot: MarketSnapshot) -> SignalDecision:
    closes = [c.close for c in snapshot.candles]
    if len(closes) < 25:
        return SignalDecision(
            product_id=snapshot.product.product_id,
            side=SignalSide.flat,
            confidence=0.0,
            reason="Not enough candles for signal generation.",
            quote_size_usd=Decimal("0"),
            risk_profile=RiskProfile.normal,
        )

    short_window = closes[-6:]
    long_window = closes[-24:]
    short_ma = sum(short_window) / Decimal(len(short_window))
    long_ma = sum(long_window) / Decimal(len(long_window))
    latest = closes[-1]
    prev = closes[-2]
    momentum = (latest - prev) / prev if prev else Decimal("0")

    if short_ma > long_ma and momentum > Decimal("0"):
        confidence = min(0.9, float((short_ma - long_ma) / long_ma * Decimal("50") + momentum * Decimal("200")))
        return SignalDecision(
            product_id=snapshot.product.product_id,
            side=SignalSide.long,
            confidence=max(confidence, 0.55),
            reason="Short MA is above long MA and last candle momentum is positive.",
            quote_size_usd=Decimal("5.00"),
            stop_loss_pct=0.012,
            take_profit_pct=0.025,
            leverage=Decimal("1"),
            risk_profile=RiskProfile.normal,
            metadata={
                "short_ma": str(short_ma),
                "long_ma": str(long_ma),
                "momentum": str(momentum),
            },
        )

    return SignalDecision(
        product_id=snapshot.product.product_id,
        side=SignalSide.flat,
        confidence=0.4,
        reason="No bullish crossover with positive momentum.",
        quote_size_usd=Decimal("0"),
        risk_profile=RiskProfile.defensive,
        metadata={
            "short_ma": str(short_ma),
            "long_ma": str(long_ma),
            "momentum": str(momentum),
        },
    )
