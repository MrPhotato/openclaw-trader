from __future__ import annotations

from decimal import Decimal

from ..models import Candle, RiskProfile, SignalDecision, SignalSide


def generate_perp_trend_signal(*, symbol: str, candles: list[Candle], max_order_quote_usd: Decimal, leverage: Decimal) -> SignalDecision:
    if len(candles) < 25:
        return SignalDecision(
            product_id=symbol,
            side=SignalSide.flat,
            confidence=0.0,
            reason="Not enough candles for perp signal generation.",
            quote_size_usd=Decimal("0"),
            leverage=leverage,
            risk_profile=RiskProfile.normal,
        )

    closes = [c.close for c in candles]
    short_window = closes[-6:]
    long_window = closes[-24:]
    short_ma = sum(short_window) / Decimal(len(short_window))
    long_ma = sum(long_window) / Decimal(len(long_window))
    latest = closes[-1]
    prev = closes[-2]
    momentum = (latest - prev) / prev if prev else Decimal("0")
    spread = (short_ma - long_ma) / long_ma if long_ma else Decimal("0")

    if short_ma > long_ma and momentum > Decimal("0"):
        confidence = min(0.92, float(spread * Decimal("45") + momentum * Decimal("180")))
        return SignalDecision(
            product_id=symbol,
            side=SignalSide.long,
            confidence=max(confidence, 0.56),
            reason="Perp trend breakout: short MA above long MA with positive momentum.",
            quote_size_usd=max_order_quote_usd,
            stop_loss_pct=0.018,
            take_profit_pct=0.04,
            leverage=leverage,
            risk_profile=RiskProfile.normal,
            metadata={"short_ma": str(short_ma), "long_ma": str(long_ma), "momentum": str(momentum)},
        )

    if short_ma < long_ma and momentum < Decimal("0"):
        confidence = min(0.92, float((long_ma - short_ma) / long_ma * Decimal("45") + abs(momentum) * Decimal("180")))
        return SignalDecision(
            product_id=symbol,
            side=SignalSide.short,
            confidence=max(confidence, 0.56),
            reason="Perp trend breakdown: short MA below long MA with negative momentum.",
            quote_size_usd=max_order_quote_usd,
            stop_loss_pct=0.018,
            take_profit_pct=0.04,
            leverage=leverage,
            risk_profile=RiskProfile.normal,
            metadata={"short_ma": str(short_ma), "long_ma": str(long_ma), "momentum": str(momentum)},
        )

    return SignalDecision(
        product_id=symbol,
        side=SignalSide.flat,
        confidence=0.40,
        reason="Perp market is range-bound; no directional edge.",
        quote_size_usd=Decimal("0"),
        leverage=leverage,
        risk_profile=RiskProfile.defensive,
        metadata={"short_ma": str(short_ma), "long_ma": str(long_ma), "momentum": str(momentum)},
    )
