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
