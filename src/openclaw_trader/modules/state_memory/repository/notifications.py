from __future__ import annotations

import json

from ....shared.infra import SqliteDatabase
from ..models import NotificationResult


class NotificationRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    def save_result(self, result: NotificationResult, payload: dict) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO notifications (notification_id, delivered, payload_json, result_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    result.notification_id,
                    int(result.delivered),
                    json.dumps(payload, ensure_ascii=False),
                    result.model_dump_json(),
                    result.delivered_at.isoformat(),
                ),
            )
