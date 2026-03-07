from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from typing import TYPE_CHECKING

from ..state import StateStore
from .formatting import (
    _as_float,
    _normalize_strategy_symbol,
    _parse_iso_datetime,
    _round_metric,
    _safe_decimal,
)

if TYPE_CHECKING:
    from . import PerpSupervisor

def _load_strategy_history(limit: int | None = None, path: Path | None = None) -> list[dict[str, Any]]:
    target = path or STRATEGY_HISTORY_JSONL
    if not target.exists():
        return []
    documents: list[dict[str, Any]] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if isinstance(payload, dict):
            documents.append(payload)
    if limit is not None and limit > 0:
        return documents[-limit:]
    return documents

def _load_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    if limit is not None and limit > 0:
        return rows[-limit:]
    return rows

def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

def _strategy_symbol_map(document: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    mapping: dict[str, dict[str, Any]] = {}
    if not isinstance(document, dict):
        return mapping
    for item in document.get("symbols") or []:
        if not isinstance(item, dict):
            continue
        symbol = _normalize_strategy_symbol(item.get("symbol"))
        if symbol:
            mapping[symbol] = item
    return mapping

def _strategy_change_summary(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    previous_symbols = _strategy_symbol_map(previous)
    current_symbols = _strategy_symbol_map(current)
    changed_symbols: list[dict[str, Any]] = []
    for symbol in sorted(set(previous_symbols) | set(current_symbols)):
        prev = previous_symbols.get(symbol) or {}
        curr = current_symbols.get(symbol) or {}
        prev_bias = str(prev.get("bias", "")).strip().lower()
        curr_bias = str(curr.get("bias", "")).strip().lower()
        prev_position = float(prev.get("max_position_share_pct", prev.get("max_position_pct", 0)) or 0.0)
        curr_position = float(curr.get("max_position_share_pct", curr.get("max_position_pct", 0)) or 0.0)
        prev_order = float(prev.get("max_order_share_pct", prev.get("max_order_pct", 0)) or 0.0)
        curr_order = float(curr.get("max_order_share_pct", curr.get("max_order_pct", 0)) or 0.0)
        if prev_bias == curr_bias and prev_position == curr_position and prev_order == curr_order:
            continue
        changed_symbols.append(
            {
                "symbol": symbol,
                "bias_from": prev_bias or None,
                "bias_to": curr_bias or None,
                "max_position_share_pct_from": prev_position,
                "max_position_share_pct_to": curr_position,
                "max_order_share_pct_from": prev_order,
                "max_order_share_pct_to": curr_order,
            }
        )
    return {
        "journaled_at": current.get("updated_at"),
        "from_version": previous.get("version") if isinstance(previous, dict) else None,
        "to_version": current.get("version"),
        "updated_at": current.get("updated_at"),
        "change_reason": current.get("change_reason"),
        "market_regime_from": previous.get("market_regime") if isinstance(previous, dict) else None,
        "market_regime_to": current.get("market_regime"),
        "risk_mode_from": previous.get("risk_mode") if isinstance(previous, dict) else None,
        "risk_mode_to": current.get("risk_mode"),
        "changed_symbols": changed_symbols,
    }

def _invalidator_set(document: dict[str, Any] | None) -> set[str]:
    if not isinstance(document, dict):
        return set()
    values = document.get("invalidators")
    if not isinstance(values, list):
        return set()
    return {str(item).strip() for item in values if str(item).strip()}

def strategy_update_is_material(
    previous: dict[str, Any] | None,
    current: dict[str, Any],
    strategy: StrategyConfig,
    *,
    reason: str | None = None,
) -> bool:
    if not isinstance(previous, dict):
        return True
    normalized_reason = str(reason or current.get("change_reason") or "").strip().lower()
    if normalized_reason.startswith("risk_shift:"):
        return True
    if str(previous.get("market_regime", "")).strip().lower() != str(current.get("market_regime", "")).strip().lower():
        return True
    if str(previous.get("risk_mode", "")).strip().lower() != str(current.get("risk_mode", "")).strip().lower():
        return True
    prev_lev = _as_float(previous.get("soft_max_leverage"), 0.0)
    curr_lev = _as_float(current.get("soft_max_leverage"), 0.0)
    if abs(curr_lev - prev_lev) >= max(strategy.material_leverage_change, 0.0):
        return True
    prev_min_lev = _as_float(previous.get("soft_min_leverage"), 1.0)
    curr_min_lev = _as_float(current.get("soft_min_leverage"), 1.0)
    if abs(curr_min_lev - prev_min_lev) >= max(strategy.material_leverage_change, 0.0):
        return True
    if _invalidator_set(previous) != _invalidator_set(current):
        return True
    summary = _strategy_change_summary(previous, current)
    for item in summary.get("changed_symbols", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("bias_from") or "").strip().lower() != str(item.get("bias_to") or "").strip().lower():
            return True
        pos_delta = abs(
            _as_float(item.get("max_position_share_pct_to"), 0.0)
            - _as_float(item.get("max_position_share_pct_from"), 0.0)
        )
        if pos_delta >= max(strategy.material_position_change_pct, 0.0):
            return True
        order_delta = abs(
            _as_float(item.get("max_order_share_pct_to"), 0.0)
            - _as_float(item.get("max_order_share_pct_from"), 0.0)
        )
        if order_delta >= max(strategy.material_order_change_pct, 0.0):
            return True
    return False

def _summarize_recent_strategy_changes(history: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    if not history:
        return []
    changes: list[dict[str, Any]] = []
    for index in range(max(0, len(history) - limit), len(history)):
        current = history[index]
        previous = history[index - 1] if index > 0 else None
        changes.append(_strategy_change_summary(previous, current))
    return changes[-limit:]

def _strategy_at_time(history: list[dict[str, Any]], when: datetime | None) -> dict[str, Any] | None:
    if when is None:
        return None
    match: dict[str, Any] | None = None
    for item in history:
        updated_at = _parse_iso_datetime(item.get("updated_at"))
        if updated_at is None or updated_at > when:
            continue
        match = item
    return match

def _strategy_alignment(symbol: str, position_side: str | None, current_strategy: dict[str, Any] | None) -> str:
    if not position_side:
        return "flat"
    item = _strategy_symbol_map(current_strategy).get(symbol)
    if not item:
        return "unknown"
    bias = str(item.get("bias", "")).strip().lower()
    if bias in {"neutral", "avoid"}:
        return "legacy"
    if (bias == "long" and position_side == "long") or (bias == "short" and position_side == "short"):
        return "aligned"
    return "conflict"

def _curve_window_summary(
    candles: list[Any],
    *,
    current_price: Decimal,
    label: str,
    start_after: int | None = None,
) -> dict[str, Any] | None:
    filtered = [item for item in candles if start_after is None or int(item.start) >= start_after]
    if not filtered:
        return None
    start_price = _safe_decimal(filtered[0].open, "0")
    high = max((_safe_decimal(item.high, "0") for item in filtered), default=Decimal("0"))
    low = min((_safe_decimal(item.low, "0") for item in filtered), default=Decimal("0"))
    return_pct = None
    if start_price > 0:
        return_pct = _round_metric(float((current_price - start_price) / start_price * Decimal("100")))
    current_vs_high_pct = None
    if high > 0:
        current_vs_high_pct = _round_metric(float((current_price - high) / high * Decimal("100")))
    current_vs_low_pct = None
    if low > 0:
        current_vs_low_pct = _round_metric(float((current_price - low) / low * Decimal("100")))
    return {
        "label": label,
        "start_at": datetime.fromtimestamp(int(filtered[0].start), UTC).isoformat(),
        "end_at": datetime.fromtimestamp(int(filtered[-1].start), UTC).isoformat(),
        "bars": len(filtered),
        "start_price": str(start_price),
        "current_price": str(current_price),
        "high": str(high),
        "low": str(low),
        "return_pct": return_pct,
        "current_vs_high_pct": current_vs_high_pct,
        "current_vs_low_pct": current_vs_low_pct,
    }

def _holding_curve_summary(
    *,
    position: dict[str, Any] | None,
    current_price: Decimal,
    candles: list[Any],
    now: datetime,
) -> dict[str, Any] | None:
    if not isinstance(position, dict):
        return None
    opened_at = _parse_iso_datetime(position.get("opened_at"))
    entry_price = _safe_decimal(position.get("entry_price"), "0")
    side = str(position.get("side", "")).strip().lower()
    if opened_at is None or entry_price <= 0 or side not in {"long", "short"}:
        return None
    start_ts = int(opened_at.timestamp())
    filtered = [item for item in candles if int(item.start) >= start_ts]
    partial_coverage = False
    if candles:
        oldest_ts = int(candles[0].start)
        partial_coverage = oldest_ts > start_ts
    high = max((_safe_decimal(item.high, "0") for item in filtered), default=current_price)
    low = min((_safe_decimal(item.low, "0") for item in filtered), default=current_price)
    price_change_pct = _round_metric(float((current_price - entry_price) / entry_price * Decimal("100")))
    if side == "long":
        favorable = _round_metric(float((high - entry_price) / entry_price * Decimal("100")))
        adverse = _round_metric(float((entry_price - low) / entry_price * Decimal("100")))
    else:
        favorable = _round_metric(float((entry_price - low) / entry_price * Decimal("100")))
        adverse = _round_metric(float((high - entry_price) / entry_price * Decimal("100")))
    return {
        "opened_at": opened_at.isoformat(),
        "entry_price": str(entry_price),
        "current_price": str(current_price),
        "position_side": side,
        "holding_duration_hours": _round_metric((now - opened_at).total_seconds() / 3600, 1),
        "price_change_since_entry_pct": price_change_pct,
        "max_favorable_move_pct": favorable,
        "max_adverse_move_pct": adverse,
        "partial_coverage": partial_coverage,
        "coverage_start_at": datetime.fromtimestamp(int(filtered[0].start), UTC).isoformat() if filtered else None,
        "bars": len(filtered),
    }

def _price_curve_memory(
    supervisor: "PerpSupervisor",
    *,
    coin: str,
    current_price: Decimal,
    position: dict[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    short_candles = supervisor.engine.candles(coin, interval="15m", lookback=96)
    medium_candles = supervisor.engine.candles(coin, interval="1h", lookback=168)
    holding_candles = medium_candles
    if isinstance(position, dict):
        opened_at = _parse_iso_datetime(position.get("opened_at"))
        if opened_at is not None:
            held_hours = max((now - opened_at).total_seconds() / 3600, 0.0)
            if held_hours <= 24:
                lookback = max(8, min(96, int(held_hours * 4) + 4))
                holding_candles = supervisor.engine.candles(coin, interval="15m", lookback=lookback)
            elif held_hours > 168:
                lookback = max(7, min(30, int(held_hours / 24) + 1))
                holding_candles = supervisor.engine.candles(coin, interval="1d", lookback=lookback)
    now_ts = int(now.timestamp())
    short_1h = _curve_window_summary(short_candles, current_price=current_price, label="1h", start_after=now_ts - 3600)
    short_4h = _curve_window_summary(short_candles, current_price=current_price, label="4h", start_after=now_ts - 4 * 3600)
    medium_24h = _curve_window_summary(medium_candles, current_price=current_price, label="24h", start_after=now_ts - 24 * 3600)
    medium_7d = _curve_window_summary(medium_candles, current_price=current_price, label="7d", start_after=now_ts - 7 * 24 * 3600)
    return {
        "short_term": [item for item in [short_1h, short_4h] if item],
        "medium_term": [item for item in [medium_24h, medium_7d] if item],
        "holding_period": _holding_curve_summary(position=position, current_price=current_price, candles=holding_candles, now=now),
    }

def _recent_orders_memory(
    state: StateStore,
    *,
    exchange: str,
    now: datetime,
    current_strategy: dict[str, Any] | None,
    limit: int = 12,
) -> dict[str, Any]:
    window_start = now - timedelta(hours=24)
    strategy_updated_at = _parse_iso_datetime((current_strategy or {}).get("updated_at"))
    if strategy_updated_at is not None and strategy_updated_at >= window_start:
        window_start = strategy_updated_at
    orders = state.list_perp_fills(exchange=exchange, since=window_start, limit=limit)
    total_realized = Decimal("0")
    total_commission = Decimal("0")
    by_product: dict[str, int] = {}
    normalized_orders: list[dict[str, Any]] = []
    for item in orders:
        product_id = str(item.get("product_id") or f"{item.get('coin', '')}-PERP").upper()
        by_product[product_id] = by_product.get(product_id, 0) + 1
        total_realized += _safe_decimal(item.get("realized_pnl_usd"), "0")
        total_commission += _safe_decimal(item.get("commission_usd"), "0")
        normalized_orders.append(
            {
                "executed_at": item.get("executed_at") or item.get("created_at"),
                "product_id": product_id,
                "action": item.get("action"),
                "side": item.get("side"),
                "notional_usd": item.get("notional_usd"),
                "price": item.get("price"),
                "realized_pnl_usd": item.get("realized_pnl_usd"),
                "commission_usd": item.get("commission_usd"),
                "order_id": item.get("order_id"),
            }
        )
    return {
        "window_start": window_start.astimezone(UTC).isoformat(),
        "window_end": now.astimezone(UTC).isoformat(),
        "count": len(normalized_orders),
        "total_realized_pnl_usd": str(total_realized),
        "total_commission_usd": str(total_commission),
        "counts_by_product": by_product,
        "orders": normalized_orders,
    }

def _position_origin_memory(
    state: StateStore,
    *,
    exchange: str,
    product_id: str,
    position: dict[str, Any] | None,
    history: list[dict[str, Any]],
    current_strategy: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(position, dict):
        return {
            "product_id": product_id,
            "has_position": False,
        }
    coin = product_id.split("-")[0]
    latest_fill = None
    recent_fills = state.list_perp_fills(exchange=exchange, coin=coin, limit=8)
    if recent_fills:
        latest_fill = recent_fills[-1]
    opened_at = _parse_iso_datetime(position.get("opened_at"))
    origin_strategy = _strategy_at_time(history, opened_at)
    return {
        "product_id": product_id,
        "has_position": True,
        "side": position.get("side"),
        "notional_usd": position.get("notional_usd"),
        "margin_used_usd": position.get("margin_used_usd"),
        "leverage": position.get("leverage"),
        "entry_price": position.get("entry_price"),
        "opened_at": opened_at.isoformat() if opened_at else position.get("opened_at"),
        "alignment_with_current_strategy": _strategy_alignment(product_id, str(position.get("side", "")).strip().lower(), current_strategy),
        "strategy_version_at_open": origin_strategy.get("version") if origin_strategy else None,
        "strategy_reason_at_open": origin_strategy.get("change_reason") if origin_strategy else None,
        "latest_fill": (
            {
                "executed_at": latest_fill.get("executed_at") or latest_fill.get("created_at"),
                "action": latest_fill.get("action"),
                "side": latest_fill.get("side"),
                "notional_usd": latest_fill.get("notional_usd"),
                "leverage": latest_fill.get("leverage"),
                "price": latest_fill.get("price"),
                "order_id": latest_fill.get("order_id"),
            }
            if latest_fill
            else None
        ),
        "provenance_note": "基于当前持仓 opened_at、近端成交和历史 strategy version 推断，未覆盖更细的多次加减仓语义。",
    }
