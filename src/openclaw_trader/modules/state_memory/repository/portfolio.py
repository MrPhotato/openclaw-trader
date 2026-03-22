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
