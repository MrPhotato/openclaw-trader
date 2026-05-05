from __future__ import annotations

import sqlite3
from pathlib import Path


class SqliteDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        # WAL allows readers to proceed concurrently with a single writer.
        # Without it (default rollback journal), any in-flight write blocks
        # every read until the write commits — verified 2026-05-05 to be
        # the cause of a sustained ~5% 5xx rate on /api/query/agents/*/latest
        # while runtime_bridge / portfolio_snapshot / risk_brake monitors
        # were all writing every few seconds against a 47 GB db.
        # busy_timeout adds a 5s retry window so transient lock collisions
        # become slow reads instead of immediate errors.
        # Both pragmas are idempotent — `journal_mode=WAL` only flips the
        # mode if not already WAL; `busy_timeout` is per-connection so it
        # has to be set on every connect.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
