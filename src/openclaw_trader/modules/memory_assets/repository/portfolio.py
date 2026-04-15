from __future__ import annotations

import json
from datetime import UTC, datetime

from ....shared.infra import SqliteDatabase
from ....shared.utils import new_id


class PortfolioRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    def save(self, trace_id: str, payload: dict) -> None:
        now = datetime.now(UTC).isoformat()
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO portfolio_snapshots (snapshot_id, trace_id, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (new_id("portfolio"), trace_id, json.dumps(payload, ensure_ascii=False), now),
            )

    def latest(self) -> dict | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT snapshot_id, trace_id, payload_json, created_at FROM portfolio_snapshots ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return {
            "snapshot_id": row["snapshot_id"],
            "trace_id": row["trace_id"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        }

    def recent(self, *, limit: int = 24) -> list[dict]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT snapshot_id, trace_id, payload_json, created_at
                FROM portfolio_snapshots
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            {
                "snapshot_id": row["snapshot_id"],
                "trace_id": row["trace_id"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def equity_timeseries(self, *, since: str, bucket_minutes: int = 15) -> list[dict]:
        """Return one equity sample per bucket_minutes interval since the given ISO timestamp.

        Uses SQL window functions to downsample millions of snapshots into a compact
        frontend-friendly series: for each (date + hour + bucket-of-minute) partition we
        keep the earliest row. Bucket math is pure string arithmetic so it works on
        SQLite's ISO-8601 text timestamps without json1-free date functions.
        """
        bucket = max(1, int(bucket_minutes))
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                WITH ranked AS (
                    SELECT
                        created_at,
                        json_extract(payload_json, '$.total_equity_usd') AS total_equity_usd,
                        ROW_NUMBER() OVER (
                            PARTITION BY (
                                substr(created_at, 1, 14) ||
                                printf('%02d', CAST(substr(created_at, 15, 2) AS INTEGER) / ? * ?)
                            )
                            ORDER BY created_at
                        ) AS rn
                    FROM portfolio_snapshots
                    WHERE created_at >= ?
                )
                SELECT created_at, total_equity_usd
                FROM ranked
                WHERE rn = 1
                ORDER BY created_at ASC
                """,
                (bucket, bucket, since),
            ).fetchall()
        return [
            {
                "created_at": row["created_at"],
                "total_equity_usd": row["total_equity_usd"],
            }
            for row in rows
        ]
