from __future__ import annotations

import json
from datetime import datetime

from ....shared.infra import SqliteDatabase
from ..models import WorkflowStateRef


class WorkflowRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    def save(self, command_id: str, workflow: WorkflowStateRef, payload: dict) -> None:
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT INTO workflows (workflow_id, command_id, trace_id, state, reason, payload_json, last_transition_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workflow_id) DO UPDATE SET
                    state=excluded.state,
                    reason=excluded.reason,
                    payload_json=excluded.payload_json,
                    last_transition_at=excluded.last_transition_at
                """,
                (
                    workflow.workflow_id,
                    command_id,
                    workflow.trace_id,
                    workflow.state,
                    workflow.reason,
                    json.dumps(payload, ensure_ascii=False),
                    workflow.last_transition_at.isoformat(),
                ),
            )

    def get_by_command(self, command_id: str) -> WorkflowStateRef | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT workflow_id, trace_id, state, reason, last_transition_at FROM workflows WHERE command_id = ?",
                (command_id,),
            ).fetchone()
        return _row_to_workflow(row)

    def get(self, trace_id: str) -> WorkflowStateRef | None:
        with self.database.connect() as conn:
            row = conn.execute(
                "SELECT workflow_id, trace_id, state, reason, last_transition_at FROM workflows WHERE trace_id = ?",
                (trace_id,),
            ).fetchone()
        return _row_to_workflow(row)


def _row_to_workflow(row) -> WorkflowStateRef | None:
    if row is None:
        return None
    return WorkflowStateRef(
        workflow_id=row["workflow_id"],
        trace_id=row["trace_id"],
        state=row["state"],
        reason=row["reason"],
        last_transition_at=datetime.fromisoformat(row["last_transition_at"]),
    )
