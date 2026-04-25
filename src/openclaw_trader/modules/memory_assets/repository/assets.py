from __future__ import annotations

import json
from datetime import UTC, datetime

from ....shared.infra import SqliteDatabase


class AssetRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    def get(self, asset_id: str) -> dict | None:
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM assets WHERE asset_id = ?", (asset_id,)).fetchone()
        return self._row_to_dict(row) if row is not None else None

    def save(
        self,
        *,
        asset_id: str,
        asset_type: str,
        trace_id: str | None,
        actor_role: str | None,
        group_key: str | None,
        source_ref: str | None,
        payload: dict,
        metadata: dict,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO assets (
                    asset_id, asset_type, trace_id, actor_role, group_key, source_ref, payload_json, metadata_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    asset_id,
                    asset_type,
                    trace_id,
                    actor_role,
                    group_key,
                    source_ref,
                    json.dumps(payload, ensure_ascii=False),
                    json.dumps(metadata, ensure_ascii=False),
                    now,
                ),
            )

    def latest(self, *, asset_type: str, actor_role: str | None = None) -> dict | None:
        sql = "SELECT * FROM assets WHERE asset_type = ?"
        params: list[object] = [asset_type]
        if actor_role:
            sql += " AND actor_role = ?"
            params.append(actor_role)
        sql += " ORDER BY created_at DESC LIMIT 1"
        with self.database.connect() as conn:
            row = conn.execute(sql, params).fetchone()
        return self._row_to_dict(row) if row is not None else None

    def recent(
        self,
        *,
        asset_type: str | None = None,
        actor_role: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        sql = "SELECT * FROM assets WHERE 1=1"
        params: list[object] = []
        if asset_type:
            sql += " AND asset_type = ?"
            params.append(asset_type)
        if actor_role:
            sql += " AND actor_role = ?"
            params.append(actor_role)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self.database.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def btc_position_marks_since(self, since_utc_iso: str) -> list[tuple[str, float]]:
        """Return (created_at_iso, BTC mark_price) tuples since the given UTC
        timestamp.

        Pulls only the two fields needed for `theoretical_profit_ceiling`
        via SQLite's `json_extract`, instead of loading the full
        portfolio_snapshot payload via `recent(limit=2000)`. The latter
        moved megabytes of JSON per refresh and dominated bridge cycle
        wall time (~78s of 88s on 2026-04-25 instrumentation).
        """
        sql = (
            "SELECT created_at, "
            "       json_extract(payload_json, '$.positions[0].raw.mark_price.value') AS mark "
            "FROM assets "
            "WHERE asset_type = 'portfolio_snapshot' "
            "  AND created_at >= ? "
            "  AND json_extract(payload_json, '$.positions[0].coin') = 'BTC' "
            "ORDER BY created_at ASC"
        )
        out: list[tuple[str, float]] = []
        with self.database.connect() as conn:
            for created_at, mark_raw in conn.execute(sql, (since_utc_iso,)).fetchall():
                if mark_raw is None:
                    continue
                try:
                    out.append((str(created_at), float(mark_raw)))
                except (TypeError, ValueError):
                    continue
        return out

    def runtime_bridge_macro_market_pair_24h(
        self, target_at_or_before_iso: str
    ) -> tuple[dict | None, dict | None]:
        """Return ((latest_brent, latest_btc), (24h_ago_brent, 24h_ago_btc)).

        Pulls only the four scalar fields needed for `regime_drift_indicators
        .brent_delta_24h_pct` / `.btc_change_pct_24h`. Replaces a previous
        `recent(asset_type='runtime_bridge_state', limit=1500)` scan that
        hauled megabytes of full bridge payload per refresh.
        """
        latest_sql = (
            "SELECT created_at, "
            "       json_extract(payload_json, '$.context.macro_prices.brent.price') AS brent, "
            "       json_extract(payload_json, '$.context.market.market.BTC.mark_price') AS btc_mark "
            "FROM assets "
            "WHERE asset_type = 'runtime_bridge_state' "
            "ORDER BY created_at DESC LIMIT 1"
        )
        prior_sql = (
            "SELECT created_at, "
            "       json_extract(payload_json, '$.context.macro_prices.brent.price') AS brent, "
            "       json_extract(payload_json, '$.context.market.market.BTC.mark_price') AS btc_mark "
            "FROM assets "
            "WHERE asset_type = 'runtime_bridge_state' "
            "  AND created_at <= ? "
            "ORDER BY created_at DESC LIMIT 1"
        )

        def _row_to_dict(row: tuple) -> dict | None:
            if row is None:
                return None
            created_at, brent, btc_mark = row
            return {
                "created_at": str(created_at),
                "brent_price": float(brent) if brent is not None else None,
                "btc_mark_price": float(btc_mark) if btc_mark is not None else None,
            }

        with self.database.connect() as conn:
            latest_row = conn.execute(latest_sql).fetchone()
            prior_row = conn.execute(prior_sql, (target_at_or_before_iso,)).fetchone()
        return _row_to_dict(latest_row), _row_to_dict(prior_row)

    @staticmethod
    def _row_to_dict(row) -> dict:
        return {
            "asset_id": row["asset_id"],
            "asset_type": row["asset_type"],
            "trace_id": row["trace_id"],
            "actor_role": row["actor_role"],
            "group_key": row["group_key"],
            "source_ref": row["source_ref"],
            "payload": json.loads(row["payload_json"]),
            "metadata": json.loads(row["metadata_json"]),
            "created_at": row["created_at"],
        }
