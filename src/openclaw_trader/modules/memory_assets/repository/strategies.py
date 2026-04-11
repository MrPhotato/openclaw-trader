from __future__ import annotations

import json
from datetime import UTC, datetime

from ....shared.infra import SqliteDatabase


class StrategyRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    def save(self, strategy_version: str, trace_id: str, payload: dict) -> None:
        now = datetime.now(UTC).isoformat()
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO strategies (strategy_version, trace_id, payload_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (strategy_version, trace_id, json.dumps(payload, ensure_ascii=False), now),
            )

    def latest(self) -> dict | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT strategy_version, trace_id, payload_json, created_at FROM strategies ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return {
            "strategy_version": row["strategy_version"],
            "trace_id": row["trace_id"],
            "payload": json.loads(row["payload_json"]),
            "created_at": row["created_at"],
        }
