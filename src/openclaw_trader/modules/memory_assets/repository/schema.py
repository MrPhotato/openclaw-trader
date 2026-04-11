from __future__ import annotations

from ....shared.infra import SqliteDatabase


def initialize_memory_assets_schema(database: SqliteDatabase) -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS workflows (
        workflow_id TEXT PRIMARY KEY,
        command_id TEXT UNIQUE NOT NULL,
        trace_id TEXT UNIQUE NOT NULL,
        state TEXT NOT NULL,
        reason TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        last_transition_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY,
        trace_id TEXT NOT NULL,
        workflow_id TEXT,
        source_module TEXT NOT NULL,
        event_type TEXT NOT NULL,
        entity_type TEXT NOT NULL,
        entity_id TEXT,
        occurred_at TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        metadata_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS strategies (
        strategy_version TEXT PRIMARY KEY,
        trace_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS portfolio_snapshots (
        snapshot_id TEXT PRIMARY KEY,
        trace_id TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS notifications (
        notification_id TEXT PRIMARY KEY,
        delivered INTEGER NOT NULL,
        payload_json TEXT NOT NULL,
        result_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS assets (
        asset_id TEXT PRIMARY KEY,
        asset_type TEXT NOT NULL,
        trace_id TEXT,
        actor_role TEXT,
        group_key TEXT,
        source_ref TEXT,
        payload_json TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_assets_type_created_at ON assets(asset_type, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_assets_role_created_at ON assets(actor_role, created_at DESC);
    CREATE TABLE IF NOT EXISTS agent_sessions (
        agent_role TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        status TEXT NOT NULL,
        last_task_kind TEXT,
        last_submission_kind TEXT,
        last_reset_command TEXT,
        last_active_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS parameters (
        name TEXT NOT NULL,
        scope TEXT NOT NULL,
        value_json TEXT NOT NULL,
        operator TEXT NOT NULL,
        reason TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (name, scope)
    );
    """
    with database.connect() as conn:
        conn.executescript(ddl)
