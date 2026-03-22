from __future__ import annotations

import json

from ....shared.infra import SqliteDatabase
from ....shared.protocols import EventEnvelope


class EventRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    def append(self, envelope: EventEnvelope) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO events (
                    event_id, trace_id, workflow_id, source_module, event_type, entity_type, entity_id, occurred_at, payload_json, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    envelope.event_id,
                    envelope.trace_id,
                    envelope.workflow_id,
                    envelope.source_module,
                    envelope.event_type,
                    envelope.entity_type,
                    envelope.entity_id,
                    envelope.occurred_at.isoformat(),
                    json.dumps(envelope.payload, ensure_ascii=False),
                    json.dumps(envelope.metadata, ensure_ascii=False),
                ),
            )

    def query(self, *, trace_id: str | None = None, module: str | None = None, limit: int = 200) -> list[dict]:
        sql = "SELECT * FROM events WHERE 1=1"
        params: list[object] = []
        if trace_id:
            sql += " AND trace_id = ?"
            params.append(trace_id)
        if module:
            sql += " AND source_module = ?"
            params.append(module)
        sql += " ORDER BY occurred_at DESC LIMIT ?"
        params.append(limit)
        with self.database.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "trace_id": row["trace_id"],
                "workflow_id": row["workflow_id"],
                "source_module": row["source_module"],
                "event_type": row["event_type"],
                "entity_type": row["entity_type"],
                "entity_id": row["entity_id"],
                "occurred_at": row["occurred_at"],
                "payload": json.loads(row["payload_json"]),
                "metadata": json.loads(row["metadata_json"]),
            }
            for row in rows
        ]
