from __future__ import annotations

import gzip
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openclaw_trader.maintenance import archive_agent_sessions, archive_db_tables, rotate_log_file, run_maintenance, split_monthly_jsonl
from openclaw_trader.state import StateStore


class MaintenanceTests(unittest.TestCase):
    def test_rotate_log_file_rotates_and_truncates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "gateway.log"
            original = "x" * 32
            path.write_text(original, encoding="utf-8")
            result = rotate_log_file(path, max_bytes=16, keep=3)
            self.assertTrue(result["rotated"])
            self.assertEqual(path.read_text(encoding="utf-8"), "")
            archive_path = path.parent / f"{path.name}.1.gz"
            self.assertTrue(archive_path.exists())
            with gzip.open(archive_path, "rt", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), original)

    def test_archive_agent_sessions_gzips_old_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            agents_root = Path(tmpdir) / "agents"
            archive_root = Path(tmpdir) / "archive"
            old_session = agents_root / "crypto-chief" / "sessions" / "old.jsonl"
            new_session = agents_root / "crypto-chief" / "sessions" / "new.jsonl"
            session_index = old_session.parent / "sessions.json"
            old_session.parent.mkdir(parents=True, exist_ok=True)
            old_session.write_text('{"message":"old"}\n', encoding="utf-8")
            new_session.write_text('{"message":"new"}\n', encoding="utf-8")
            session_index.write_text(
                json.dumps(
                    {
                        "agent:crypto-chief:old": {
                            "sessionId": "old",
                            "sessionFile": str(old_session),
                        },
                        "agent:crypto-chief:new": {
                            "sessionId": "new",
                            "sessionFile": str(new_session),
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            now = datetime(2026, 3, 5, 0, 0, tzinfo=UTC)
            old_timestamp = (now - timedelta(days=30)).timestamp()
            os.utime(old_session, (old_timestamp, old_timestamp))
            result = archive_agent_sessions(
                agents_root=agents_root,
                archive_root=archive_root,
                hot_days=14,
                now=now,
            )
            self.assertEqual(result["archived"], 1)
            self.assertFalse(old_session.exists())
            archived = archive_root / "crypto-chief" / "2026-02" / "old.jsonl.gz"
            self.assertTrue(archived.exists())
            with gzip.open(archived, "rt", encoding="utf-8") as handle:
                self.assertIn('"message":"old"', handle.read())
            self.assertTrue(new_session.exists())
            index_payload = json.loads(session_index.read_text(encoding="utf-8"))
            self.assertNotIn("agent:crypto-chief:old", index_payload)
            self.assertIn("agent:crypto-chief:new", index_payload)

    def test_split_monthly_jsonl_archives_prior_months(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "strategy-history.jsonl"
            archive_root = Path(tmpdir) / "archive"
            path.write_text(
                "\n".join(
                    [
                        '{"version":1,"updated_at":"2026-02-28T12:00:00+00:00"}',
                        '{"version":2,"updated_at":"2026-03-01T00:00:00+00:00"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            result = split_monthly_jsonl(
                path,
                archive_root=archive_root,
                timestamp_keys=("updated_at",),
                now=datetime(2026, 3, 5, 0, 0, tzinfo=UTC),
            )
            self.assertEqual(result["archived_lines"], 1)
            self.assertEqual(result["kept_lines"], 1)
            self.assertIn('"version":2', path.read_text(encoding="utf-8"))
            archived = archive_root / "strategy-history-2026-02.jsonl.gz"
            self.assertTrue(archived.exists())
            with gzip.open(archived, "rt", encoding="utf-8") as handle:
                self.assertIn('"version":1', handle.read())

    def test_archive_db_tables_moves_old_rows_to_archive_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "trader.db"
            StateStore(db_path)
            now = datetime(2026, 3, 5, 0, 0, tzinfo=UTC)
            old_created_at = (now - timedelta(days=60)).isoformat()
            recent_created_at = (now - timedelta(days=5)).isoformat()
            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    "INSERT INTO news_events (created_at, source, title, url, severity, payload) VALUES (?, ?, ?, ?, ?, ?)",
                    (old_created_at, "old-source", "old", "https://example.com/old", "low", "{}"),
                )
                connection.execute(
                    "INSERT INTO news_events (created_at, source, title, url, severity, payload) VALUES (?, ?, ?, ?, ?, ?)",
                    (recent_created_at, "new-source", "new", "https://example.com/new", "low", "{}"),
                )
                connection.commit()
            archive_root = Path(tmpdir) / "archive"
            result = archive_db_tables(
                db_path=db_path,
                archive_root=archive_root,
                retention_days={"news_events": 45},
                now=now,
            )
            self.assertEqual(result["archived_rows"], 1)
            with sqlite3.connect(db_path) as connection:
                remaining = connection.execute("SELECT title FROM news_events ORDER BY created_at").fetchall()
            self.assertEqual(remaining, [("new",)])
            archived_db = archive_root / "trader-archive-2026-01.db"
            self.assertTrue(archived_db.exists())
            with sqlite3.connect(archived_db) as connection:
                archived = connection.execute("SELECT title FROM news_events ORDER BY created_at").fetchall()
            self.assertEqual(archived, [("old",)])

    def test_run_maintenance_skips_session_archival(self) -> None:
        result = run_maintenance(now=datetime(2026, 3, 5, 0, 0, tzinfo=UTC))
        self.assertTrue(result["sessions"]["skipped"])
        self.assertFalse(result["sessions"]["enabled"])
        self.assertEqual(result["sessions"]["reason"], "session_archival_disabled")
