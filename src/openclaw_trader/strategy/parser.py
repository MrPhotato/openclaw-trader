from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .formatting import _normalize_strategy_symbol
from .rewrite import _normalize_scheduled_rechecks

def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        raise ValueError("empty strategy response")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("strategy response does not contain json object")
    return json.loads(text[start : end + 1])

def parse_strategy_response(
    text: str,
    *,
    now: datetime,
    strategy_date: str,
    reason: str,
    allowed_symbols: set[str] | None = None,
    recommended_limits: dict[str, dict[str, Any]] | None = None,
    current_strategy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _extract_json_object(text)
    allowed_biases = {"long", "neutral", "short", "avoid"}
    recommended_limits = recommended_limits or {}
    market_regime = str(payload.get("market_regime", "")).strip()
    if not market_regime:
        raise ValueError("strategy response missing market_regime")
    risk_mode = str(payload.get("risk_mode", "aggressive")).strip()
    if not risk_mode:
        risk_mode = "aggressive"
    raw_symbols = payload.get("symbols")
    if not isinstance(raw_symbols, list):
        raise ValueError("strategy response missing symbols array")
    normalized_allowed_symbols: set[str] | None = None
    if allowed_symbols is not None:
        normalized_allowed_symbols = set()
        for item in allowed_symbols:
            normalized = _normalize_strategy_symbol(item)
            if normalized:
                normalized_allowed_symbols.add(normalized)
    meta = recommended_limits.get("__meta__", {}) if isinstance(recommended_limits, dict) else {}
    symbols = raw_symbols
    cleaned_symbols: list[dict[str, Any]] = []
    for item in symbols:
        raw_symbol = str(item.get("symbol", "")).strip().upper()
        normalized_symbol = _normalize_strategy_symbol(raw_symbol)
        filter_symbol = normalized_symbol or raw_symbol
        if normalized_allowed_symbols is not None and filter_symbol not in normalized_allowed_symbols:
            continue
        symbol = raw_symbol or normalized_symbol
        if raw_symbol.endswith("-PERP-INTX"):
            symbol = normalized_symbol
        bias = str(item.get("bias", "neutral")).strip().lower()
        if bias not in allowed_biases:
            raise ValueError(f"invalid bias for {symbol or 'unknown'}: {bias}")
        raw_position_share_pct = float(item.get("max_position_share_pct", item.get("max_position_pct", 0)))
        raw_order_share_pct = float(item.get("max_order_share_pct", item.get("max_order_pct", 0)))
        limits = recommended_limits.get(symbol) or (
            recommended_limits.get(filter_symbol) if filter_symbol and filter_symbol != symbol else None
        )
        if limits:
            rec_position_share_pct = float(
                limits.get("max_position_share_pct", limits.get("max_position_pct", raw_position_share_pct))
            )
            rec_order_share_pct = float(
                limits.get("max_order_share_pct", limits.get("max_order_pct", raw_order_share_pct))
            )
            if raw_position_share_pct <= 0:
                raw_position_share_pct = rec_position_share_pct
            if raw_order_share_pct <= 0:
                raw_order_share_pct = rec_order_share_pct
            raw_order_share_pct = min(raw_order_share_pct, raw_position_share_pct)
        cleaned_symbols.append(
            {
                "symbol": symbol,
                "bias": bias,
                "max_position_share_pct": raw_position_share_pct,
                "max_order_share_pct": raw_order_share_pct,
                "thesis": str(item.get("thesis", "")).strip(),
            }
        )
    if not cleaned_symbols:
        raise ValueError("strategy response does not contain any tracked symbols")
    hard_total_exposure_pct = None
    hard_max_leverage = None
    portfolio_total_equity_usd = None
    if recommended_limits:
        try:
            hard_total_exposure_pct = float(meta.get("hard_total_exposure_pct")) if meta.get("hard_total_exposure_pct") is not None else None
        except Exception:
            hard_total_exposure_pct = None
        try:
            hard_max_order_share_pct = float(meta.get("hard_max_order_share_pct")) if meta.get("hard_max_order_share_pct") is not None else None
        except Exception:
            hard_max_order_share_pct = None
        try:
            hard_max_leverage = float(meta.get("hard_max_leverage")) if meta.get("hard_max_leverage") is not None else None
        except Exception:
            hard_max_leverage = None
        try:
            portfolio_total_equity_usd = float(meta.get("portfolio_total_equity_usd")) if meta.get("portfolio_total_equity_usd") is not None else None
        except Exception:
            portfolio_total_equity_usd = None
    else:
        hard_max_order_share_pct = None
    if hard_total_exposure_pct is not None:
        hard_total_exposure_pct = min(max(hard_total_exposure_pct, 0.0), 100.0)
    if hard_max_order_share_pct is not None:
        hard_max_order_share_pct = min(max(hard_max_order_share_pct, 0.0), 100.0)
    hard_min_leverage = 1.0
    if hard_max_leverage is not None:
        hard_max_leverage = max(hard_max_leverage, hard_min_leverage)
    try:
        soft_max_leverage = float(payload.get("soft_max_leverage", hard_max_leverage or hard_min_leverage))
    except Exception:
        soft_max_leverage = hard_max_leverage or hard_min_leverage
    if hard_max_leverage is not None:
        soft_max_leverage = min(soft_max_leverage, hard_max_leverage)
    soft_max_leverage = round(max(soft_max_leverage, hard_min_leverage), 2)
    try:
        soft_min_leverage = float(payload.get("soft_min_leverage", hard_min_leverage))
    except Exception:
        soft_min_leverage = hard_min_leverage
    if hard_max_leverage is not None:
        soft_min_leverage = min(soft_min_leverage, hard_max_leverage)
    soft_min_leverage = round(max(soft_min_leverage, hard_min_leverage), 2)
    if soft_max_leverage < soft_min_leverage:
        soft_max_leverage = soft_min_leverage
    margin_budget_usd = None
    notional_budget_usd = None
    if portfolio_total_equity_usd is not None:
        margin_budget_usd = portfolio_total_equity_usd * ((hard_total_exposure_pct or 100.0) / 100)
        notional_budget_usd = margin_budget_usd * soft_max_leverage
    for item in cleaned_symbols:
        if item["bias"] in {"neutral", "avoid"}:
            item["max_position_share_pct"] = 0.0
            item["max_order_share_pct"] = 0.0
            continue
        if notional_budget_usd is not None and notional_budget_usd <= 0:
            item["max_position_share_pct"] = 0.0
            item["max_order_share_pct"] = 0.0
            continue
        symbol_key = str(item["symbol"])
        normalized_symbol_key = _normalize_strategy_symbol(symbol_key)
        limits = recommended_limits.get(symbol_key) or (
            recommended_limits.get(normalized_symbol_key) if normalized_symbol_key and normalized_symbol_key != symbol_key else None
        ) or {}
        try:
            minimum_trade_notional_usd = float(limits.get("minimum_trade_notional_usd")) if limits.get("minimum_trade_notional_usd") is not None else None
        except Exception:
            minimum_trade_notional_usd = None
        minimum_actionable_share_pct = 0.0
        if minimum_trade_notional_usd is not None and notional_budget_usd and notional_budget_usd > 0:
            minimum_actionable_share_pct = minimum_trade_notional_usd / notional_budget_usd * 100
        elif limits.get("minimum_actionable_share_pct_of_exposure_budget") is not None:
            try:
                minimum_actionable_share_pct = float(limits.get("minimum_actionable_share_pct_of_exposure_budget") or 0.0)
            except Exception:
                minimum_actionable_share_pct = 0.0
        if (
            minimum_actionable_share_pct > 0
            and (
                0 < item["max_position_share_pct"] < minimum_actionable_share_pct
                or 0 < item["max_order_share_pct"] < minimum_actionable_share_pct
            )
        ):
            item["max_position_share_pct"] = 0.0
            item["max_order_share_pct"] = 0.0
    watchlist = payload.get("watchlist_suggestions") or {}
    suggested_add = sorted(
        {
            str(item).upper()
            for item in watchlist.get("add", [])
            if str(item).strip()
        }
    )
    suggested_remove = sorted(
        {
            str(item).upper()
            for item in watchlist.get("remove", [])
            if str(item).strip()
        }
    )
    scheduled_rechecks = _normalize_scheduled_rechecks(
        payload.get("scheduled_rechecks") if "scheduled_rechecks" in payload else None,
        now=now,
        current_items=(current_strategy or {}).get("scheduled_rechecks")
        if isinstance(current_strategy, dict)
        else None,
    )
    return {
        "strategy_date": str(payload.get("strategy_date") or strategy_date),
        "updated_at": now.astimezone(UTC).isoformat(),
        "change_reason": reason,
        "market_regime": market_regime,
        "risk_mode": risk_mode,
        "soft_min_leverage": soft_min_leverage,
        "soft_max_leverage": soft_max_leverage,
        "summary": str(payload.get("summary", "")).strip(),
        "invalidators": [str(item).strip() for item in payload.get("invalidators", []) if str(item).strip()],
        "watchlist_suggestions": {
            "add": suggested_add,
            "remove": suggested_remove,
            "reason": str(watchlist.get("reason", "")).strip(),
        },
        "scheduled_rechecks": scheduled_rechecks,
        "symbols": cleaned_symbols,
        **({"global_max_order_share_pct": hard_max_order_share_pct} if hard_max_order_share_pct is not None else {}),
    }
