from __future__ import annotations

import json
from datetime import UTC, datetime

from ....shared.infra import SqliteDatabase


class ParameterRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    def list(self) -> list[dict]:
        with self.database.connect() as conn:
            rows = conn.execute(
                "SELECT name, scope, value_json, operator, reason, updated_at FROM parameters ORDER BY name, scope"
            ).fetchall()
        return [
            {
                "name": row["name"],
                "scope": row["scope"],
                "value": json.loads(row["value_json"]),
                "operator": row["operator"],
                "reason": row["reason"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def save(self, name: str, scope: str, value: dict, *, operator: str, reason: str) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO parameters (name, scope, value_json, operator, reason, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    name,
                    scope,
                    json.dumps(value, ensure_ascii=False),
                    operator,
                    reason,
                    datetime.now(UTC).isoformat(),
                ),
            )
