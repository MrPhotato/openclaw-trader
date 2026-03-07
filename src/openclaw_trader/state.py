from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .config import DB_PATH, STATE_DIR
from .models import NewsItem, OrderResult, RiskEvaluation, SignalDecision


SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  product_id TEXT NOT NULL,
  side TEXT NOT NULL,
  confidence REAL NOT NULL,
  quote_size_usd TEXT,
  reason TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS risk_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  product_id TEXT NOT NULL,
  approved INTEGER NOT NULL,
  reason TEXT NOT NULL,
  max_allowed_quote_usd TEXT NOT NULL,
  blocked_rules TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  order_id TEXT,
  product_id TEXT,
  side TEXT,
  success INTEGER NOT NULL,
  message TEXT,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS news_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  source TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  severity TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS daily_equity_baselines (
  trading_day TEXT PRIMARY KEY,
  baseline_equity_usd TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notification_marks (
  key TEXT PRIMARY KEY,
  fingerprint TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_entries (
  product_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  active INTEGER NOT NULL,
  quote_size_usd TEXT NOT NULL,
  side TEXT NOT NULL,
  reason TEXT NOT NULL,
  stop_loss_pct REAL,
  take_profit_pct REAL,
  confidence REAL,
  source TEXT NOT NULL,
  preview_id TEXT,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kv_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS perp_paper_positions (
  exchange TEXT NOT NULL,
  coin TEXT NOT NULL,
  active INTEGER NOT NULL,
  side TEXT NOT NULL,
  notional_usd TEXT NOT NULL,
  leverage TEXT NOT NULL,
  entry_price TEXT NOT NULL,
  quantity TEXT NOT NULL,
  margin_used_usd TEXT NOT NULL,
  opened_at TEXT NOT NULL,
  payload TEXT NOT NULL,
  PRIMARY KEY (exchange, coin)
);
CREATE TABLE IF NOT EXISTS perp_paper_fills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  exchange TEXT NOT NULL,
  coin TEXT NOT NULL,
  action TEXT NOT NULL,
  side TEXT,
  notional_usd TEXT,
  leverage TEXT,
  price TEXT,
  realized_pnl_usd TEXT,
  payload TEXT NOT NULL
);
"""


class StateStore:
    def __init__(self, db_path: Path = DB_PATH):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def record_decision(self, decision: SignalDecision) -> None:
        payload = decision.model_dump(mode="json")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO decisions (created_at, product_id, side, confidence, quote_size_usd, reason, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    decision.product_id,
                    decision.side.value,
                    decision.confidence,
                    str(decision.quote_size_usd or ""),
                    decision.reason,
                    json.dumps(payload, ensure_ascii=True),
                ),
            )
            conn.commit()

    def record_risk(self, product_id: str, risk: RiskEvaluation) -> None:
        payload = risk.model_dump(mode="json")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO risk_checks (created_at, product_id, approved, reason, max_allowed_quote_usd, blocked_rules, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    product_id,
                    1 if risk.approved else 0,
                    risk.reason,
                    str(risk.max_allowed_quote_usd),
                    json.dumps(risk.blocked_rules, ensure_ascii=True),
                    json.dumps(payload, ensure_ascii=True),
                ),
            )
            conn.commit()

    def record_order(self, result: OrderResult) -> None:
        payload = result.model_dump(mode="json")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO orders (created_at, order_id, product_id, side, success, message, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    result.order_id,
                    result.product_id,
                    result.side,
                    1 if result.success else 0,
                    result.message,
                    json.dumps(payload, ensure_ascii=True),
                ),
            )
            conn.commit()

    def record_news(self, item: NewsItem, *, now: datetime | None = None) -> None:
        timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        payload = item.model_dump(mode="json")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO news_events (created_at, source, title, url, severity, payload) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    timestamp,
                    item.source,
                    item.title,
                    item.url,
                    item.severity,
                    json.dumps(payload, ensure_ascii=True),
                ),
            )
            conn.commit()

    def record_news_if_new(self, item: NewsItem, *, now: datetime | None = None) -> bool:
        timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT 1
                FROM news_events
                WHERE source = ? AND title = ? AND url = ?
                LIMIT 1
                """,
                (item.source, item.title, item.url),
            ).fetchone()
            if existing:
                return False
            payload = item.model_dump(mode="json")
            conn.execute(
                "INSERT INTO news_events (created_at, source, title, url, severity, payload) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    timestamp,
                    item.source,
                    item.title,
                    item.url,
                    item.severity,
                    json.dumps(payload, ensure_ascii=True),
                ),
            )
            conn.commit()
            return True

    def list_recent_news(
        self,
        max_age_minutes: int = 24 * 60,
        limit: int = 50,
        *,
        now: datetime | None = None,
    ) -> list[NewsItem]:
        reference_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        cutoff = reference_now - timedelta(minutes=max_age_minutes)
        items: list[NewsItem] = []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT created_at, payload
                FROM news_events
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (max(limit * 5, 100),),
            ).fetchall()
        for row in rows:
            created_at = datetime.fromisoformat(str(row[0]))
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            payload = json.loads(str(row[1]))
            item = NewsItem.model_validate(payload)
            effective_time = item.published_at or created_at
            if effective_time.tzinfo is None:
                effective_time = effective_time.replace(tzinfo=timezone.utc)
            if effective_time < cutoff:
                continue
            items.append(item)
            if len(items) >= limit:
                break
        return items

    def get_or_create_daily_equity_baseline(self, trading_day: str, baseline_equity_usd: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT baseline_equity_usd FROM daily_equity_baselines WHERE trading_day = ?",
                (trading_day,),
            ).fetchone()
            if row:
                return str(row[0])
            conn.execute(
                "INSERT INTO daily_equity_baselines (trading_day, baseline_equity_usd, created_at) VALUES (?, ?, ?)",
                (
                    trading_day,
                    baseline_equity_usd,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
            return baseline_equity_usd

    def should_emit_notification(
        self,
        key: str,
        fingerprint: str,
        cooldown_minutes: int,
        *,
        now: datetime | None = None,
    ) -> bool:
        reference_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT fingerprint, updated_at FROM notification_marks WHERE key = ?",
                (key,),
            ).fetchone()
            if row:
                prior_fingerprint = str(row[0])
                prior_updated_at = datetime.fromisoformat(str(row[1]))
                if prior_updated_at.tzinfo is None:
                    prior_updated_at = prior_updated_at.replace(tzinfo=timezone.utc)
                if prior_fingerprint == fingerprint and reference_now - prior_updated_at < timedelta(minutes=cooldown_minutes):
                    return False
            conn.execute(
                "INSERT OR REPLACE INTO notification_marks (key, fingerprint, updated_at) VALUES (?, ?, ?)",
                (key, fingerprint, reference_now.isoformat()),
            )
            conn.commit()
            return True

    def upsert_pending_entry(
        self,
        *,
        product_id: str,
        quote_size_usd: str,
        side: str,
        reason: str,
        stop_loss_pct: float | None,
        take_profit_pct: float | None,
        confidence: float | None,
        source: str,
        preview_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pending_entries (
                  product_id, created_at, updated_at, active, quote_size_usd, side, reason,
                  stop_loss_pct, take_profit_pct, confidence, source, preview_id, payload
                ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(product_id) DO UPDATE SET
                  updated_at=excluded.updated_at,
                  active=1,
                  quote_size_usd=excluded.quote_size_usd,
                  side=excluded.side,
                  reason=excluded.reason,
                  stop_loss_pct=excluded.stop_loss_pct,
                  take_profit_pct=excluded.take_profit_pct,
                  confidence=excluded.confidence,
                  source=excluded.source,
                  preview_id=excluded.preview_id,
                  payload=excluded.payload
                """,
                (
                    product_id,
                    now,
                    now,
                    quote_size_usd,
                    side,
                    reason,
                    stop_loss_pct,
                    take_profit_pct,
                    confidence,
                    source,
                    preview_id,
                    json.dumps(payload, ensure_ascii=True),
                ),
            )
            conn.commit()

    def get_pending_entry(self, product_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT created_at, updated_at, active, quote_size_usd, side, reason,
                       stop_loss_pct, take_profit_pct, confidence, source, preview_id, payload
                FROM pending_entries
                WHERE product_id = ? AND active = 1
                """,
                (product_id,),
            ).fetchone()
            if not row:
                return None
            payload = json.loads(str(row[11]))
            payload.update(
                {
                    "product_id": product_id,
                    "created_at": str(row[0]),
                    "updated_at": str(row[1]),
                    "active": bool(row[2]),
                    "quote_size_usd": str(row[3]),
                    "side": str(row[4]),
                    "reason": str(row[5]),
                    "stop_loss_pct": row[6],
                    "take_profit_pct": row[7],
                    "confidence": row[8],
                    "source": str(row[9]),
                    "preview_id": row[10],
                }
            )
            return payload

    def clear_pending_entry(self, product_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE pending_entries SET active = 0, updated_at = ? WHERE product_id = ?",
                (datetime.now(timezone.utc).isoformat(), product_id),
            )
            conn.commit()

    def get_value(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM kv_state WHERE key = ?",
                (key,),
            ).fetchone()
            return str(row[0]) if row else None

    def set_value(self, key: str, value: str, *, now: datetime | None = None) -> None:
        timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO kv_state (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, timestamp),
            )
            conn.commit()

    def acquire_timed_lock(
        self,
        key: str,
        *,
        ttl_seconds: int,
        now: datetime | None = None,
    ) -> bool:
        reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        cutoff = reference - timedelta(seconds=max(ttl_seconds, 0))
        timestamp = reference.isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT updated_at FROM kv_state WHERE key = ?",
                (key,),
            ).fetchone()
            if row:
                try:
                    updated_at = datetime.fromisoformat(str(row[0]))
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=timezone.utc)
                    updated_at = updated_at.astimezone(timezone.utc)
                except Exception:
                    updated_at = datetime.min.replace(tzinfo=timezone.utc)
                if updated_at >= cutoff:
                    conn.commit()
                    return False
            conn.execute(
                "INSERT OR REPLACE INTO kv_state (key, value, updated_at) VALUES (?, ?, ?)",
                (key, timestamp, timestamp),
            )
            conn.commit()
            return True

    def delete_value(self, key: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM kv_state WHERE key = ?", (key,))
            conn.commit()

    def get_perp_paper_position(self, exchange: str, coin: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT side, notional_usd, leverage, entry_price, quantity,
                       margin_used_usd, opened_at, payload
                FROM perp_paper_positions
                WHERE exchange = ? AND coin = ? AND active = 1
                """,
                (exchange, coin),
            ).fetchone()
            if not row:
                return None
            payload = json.loads(str(row[7]))
            payload.update(
                {
                    "exchange": exchange,
                    "coin": coin,
                    "side": str(row[0]),
                    "notional_usd": str(row[1]),
                    "leverage": str(row[2]),
                    "entry_price": str(row[3]),
                    "quantity": str(row[4]),
                    "margin_used_usd": str(row[5]),
                    "opened_at": str(row[6]),
                }
            )
            return payload

    def upsert_perp_paper_position(
        self,
        *,
        exchange: str,
        coin: str,
        side: str,
        notional_usd: str,
        leverage: str,
        entry_price: str,
        quantity: str,
        margin_used_usd: str,
        opened_at: str,
        payload: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO perp_paper_positions (
                  exchange, coin, active, side, notional_usd, leverage, entry_price,
                  quantity, margin_used_usd, opened_at, payload
                ) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(exchange, coin) DO UPDATE SET
                  active=1,
                  side=excluded.side,
                  notional_usd=excluded.notional_usd,
                  leverage=excluded.leverage,
                  entry_price=excluded.entry_price,
                  quantity=excluded.quantity,
                  margin_used_usd=excluded.margin_used_usd,
                  opened_at=excluded.opened_at,
                  payload=excluded.payload
                """,
                (
                    exchange,
                    coin,
                    side,
                    notional_usd,
                    leverage,
                    entry_price,
                    quantity,
                    margin_used_usd,
                    opened_at,
                    json.dumps(payload, ensure_ascii=True),
                ),
            )
            conn.commit()

    def clear_perp_paper_position(self, exchange: str, coin: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE perp_paper_positions SET active = 0 WHERE exchange = ? AND coin = ?",
                (exchange, coin),
            )
            conn.commit()

    def record_perp_paper_fill(
        self,
        *,
        exchange: str,
        coin: str,
        action: str,
        side: str | None,
        notional_usd: str | None,
        leverage: str | None,
        price: str | None,
        realized_pnl_usd: str | None,
        payload: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO perp_paper_fills (
                  created_at, exchange, coin, action, side, notional_usd,
                  leverage, price, realized_pnl_usd, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    datetime.now(timezone.utc).isoformat(),
                    exchange,
                    coin,
                    action,
                    side,
                    notional_usd,
                    leverage,
                    price,
                    realized_pnl_usd,
                    json.dumps(payload, ensure_ascii=True),
                ),
            )
            conn.commit()

    def list_perp_fills(
        self,
        *,
        exchange: str | None = None,
        coin: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        query = """
            SELECT created_at, exchange, coin, action, side, notional_usd, leverage, price, realized_pnl_usd, payload
            FROM perp_paper_fills
        """
        clauses: list[str] = []
        params: list[Any] = []
        if exchange:
            clauses.append("exchange = ?")
            params.append(exchange)
        if coin:
            clauses.append("coin = ?")
            params.append(coin.upper())
        if since is not None:
            clauses.append("created_at >= ?")
            params.append(since.astimezone(timezone.utc).isoformat())
        if until is not None:
            clauses.append("created_at <= ?")
            params.append(until.astimezone(timezone.utc).isoformat())
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()

        items: list[dict[str, Any]] = []
        for row in reversed(rows):
            payload = json.loads(str(row[9]))
            fills = payload.get("fills") or []
            first_fill = fills[0] if fills else {}
            executed_times = [str(fill["trade_time"]) for fill in fills if fill.get("trade_time")]
            size_total: Decimal | None = None
            commission_total: Decimal | None = None
            size_in_quote = None
            for fill in fills:
                raw_size = fill.get("size")
                if raw_size not in (None, ""):
                    try:
                        size_total = (size_total or Decimal("0")) + Decimal(str(raw_size))
                    except (InvalidOperation, ValueError):
                        pass
                raw_commission = fill.get("commission")
                if raw_commission not in (None, ""):
                    try:
                        commission_total = (commission_total or Decimal("0")) + Decimal(str(raw_commission))
                    except (InvalidOperation, ValueError):
                        pass
                if size_in_quote is None and "size_in_quote" in fill:
                    size_in_quote = fill.get("size_in_quote")
            items.append(
                {
                    "created_at": str(row[0]),
                    "executed_at": min(executed_times) if executed_times else first_fill.get("trade_time"),
                    "exchange": str(row[1]),
                    "coin": str(row[2]),
                    "action": str(row[3]),
                    "side": str(row[4]) if row[4] is not None else None,
                    "notional_usd": str(row[5]) if row[5] is not None else None,
                    "leverage": str(row[6]) if row[6] is not None else None,
                    "price": str(row[7]) if row[7] is not None else None,
                    "realized_pnl_usd": str(row[8]) if row[8] is not None else None,
                    "order_id": first_fill.get("order_id") or payload.get("order", {}).get("order_id"),
                    "product_id": first_fill.get("product_id") or payload.get("order", {}).get("product_id"),
                    "size": str(size_total) if size_total is not None else first_fill.get("size"),
                    "size_in_quote": size_in_quote if size_in_quote is not None else first_fill.get("size_in_quote"),
                    "commission_usd": str(commission_total) if commission_total is not None else first_fill.get("commission"),
                    "liquidity_indicator": first_fill.get("liquidity_indicator"),
                    "fill_source": first_fill.get("fillSource"),
                    "payload": payload,
                }
            )
        return items
