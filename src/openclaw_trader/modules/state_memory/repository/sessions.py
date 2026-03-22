from __future__ import annotations

from datetime import UTC, datetime

from ....shared.infra import SqliteDatabase
from ..models import AgentSessionState


class AgentSessionRepository:
    def __init__(self, database: SqliteDatabase) -> None:
        self.database = database

    def save(self, state: AgentSessionState) -> None:
        last_active_at = state.last_active_at or datetime.now(UTC)
        with self.database.connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO agent_sessions (
                    agent_role, session_id, status, last_task_kind, last_submission_kind, last_reset_command, last_active_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    state.agent_role,
                    state.session_id,
                    state.status,
                    state.last_task_kind,
                    state.last_submission_kind,
                    state.last_reset_command,
                    last_active_at.isoformat(),
                ),
            )

    def get(self, agent_role: str) -> AgentSessionState | None:
        with self.database.connect() as conn:
            row = conn.execute(
                """
                SELECT agent_role, session_id, status, last_task_kind, last_submission_kind, last_reset_command, last_active_at
                FROM agent_sessions
                WHERE agent_role = ?
                """,
                (agent_role,),
            ).fetchone()
        if row is None:
            return None
        return AgentSessionState(
            agent_role=row["agent_role"],
            session_id=row["session_id"],
            status=row["status"],
            last_task_kind=row["last_task_kind"],
            last_submission_kind=row["last_submission_kind"],
            last_reset_command=row["last_reset_command"],
            last_active_at=datetime.fromisoformat(row["last_active_at"]),
        )

    def list(self) -> list[dict]:
        with self.database.connect() as conn:
            rows = conn.execute(
                """
                SELECT agent_role, session_id, status, last_task_kind, last_submission_kind, last_reset_command, last_active_at
                FROM agent_sessions
                ORDER BY agent_role ASC
                """
            ).fetchall()
        return [
            AgentSessionState(
                agent_role=row["agent_role"],
                session_id=row["session_id"],
                status=row["status"],
                last_task_kind=row["last_task_kind"],
                last_submission_kind=row["last_submission_kind"],
                last_reset_command=row["last_reset_command"],
                last_active_at=datetime.fromisoformat(row["last_active_at"]),
            ).model_dump(mode="json")
            for row in rows
        ]
