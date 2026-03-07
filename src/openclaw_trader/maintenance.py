from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import DB_PATH, LOG_DIR, REPORT_DIR, RUNTIME_ROOT
from .state import SCHEMA


OPENCLAW_ROOT = Path.home() / ".openclaw"
AGENTS_ROOT = OPENCLAW_ROOT / "agents"
AGENT_SESSION_ARCHIVE_ROOT = OPENCLAW_ROOT / "archive" / "agent-sessions"
REPORT_ARCHIVE_ROOT = REPORT_DIR / "archive"
DB_ARCHIVE_ROOT = RUNTIME_ROOT / "state" / "archive"

LOG_ROTATION_MAX_BYTES = 10 * 1024 * 1024
LOG_ROTATION_KEEP = 7
SESSION_ARCHIVE_AFTER_DAYS = 14
SESSION_ARCHIVE_ENABLED = False

LOG_TARGETS = [
    LOG_DIR / "trader-dispatcher.stderr.log",
    LOG_DIR / "trader-dispatcher.stdout.log",
    LOG_DIR / "trader.stderr.log",
    LOG_DIR / "trader.stdout.log",
    LOG_DIR / "trader-maintenance.stderr.log",
    LOG_DIR / "trader-maintenance.stdout.log",
    OPENCLAW_ROOT / "logs" / "gateway.log",
    OPENCLAW_ROOT / "logs" / "gateway.err.log",
    OPENCLAW_ROOT / "logs" / "config-audit.jsonl",
    OPENCLAW_ROOT / "logs" / "wecom-app-cloudflared.log",
    OPENCLAW_ROOT / "logs" / "wecom-app-cloudflared.stderr.log",
    OPENCLAW_ROOT / "logs" / "wecom-app-cloudflared.stdout.log",
]

MONTHLY_JSONL_TARGETS: dict[str, tuple[Path, tuple[str, ...]]] = {
    "strategy_history": (REPORT_DIR / "strategy-history.jsonl", ("updated_at", "strategy_date")),
    "strategy_change_log": (REPORT_DIR / "strategy-change-log.jsonl", ("journaled_at", "updated_at")),
    "position_journal": (REPORT_DIR / "position-journal.jsonl", ("journaled_at",)),
}

DB_RETENTION_DAYS: dict[str, int] = {
    "news_events": 45,
    "decisions": 30,
    "risk_checks": 30,
    "orders": 365,
    "perp_paper_fills": 365,
}


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    normalized = str(value).strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _month_key(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m")


def rotate_log_file(path: Path, *, max_bytes: int = LOG_ROTATION_MAX_BYTES, keep: int = LOG_ROTATION_KEEP) -> dict[str, Any]:
    result = {
        "path": str(path),
        "exists": path.exists(),
        "rotated": False,
        "size_before": path.stat().st_size if path.exists() else 0,
        "archives_kept": keep,
    }
    if not path.exists() or path.stat().st_size <= max_bytes:
        return result
    for index in range(keep, 0, -1):
        source = path.parent / f"{path.name}.{index}.gz"
        target = path.parent / f"{path.name}.{index + 1}.gz"
        if index == keep and source.exists():
            source.unlink()
            continue
        if source.exists():
            source.replace(target)
    archive_path = path.parent / f"{path.name}.1.gz"
    with path.open("rb") as source_handle, gzip.open(archive_path, "wb") as archive_handle:
        shutil.copyfileobj(source_handle, archive_handle)
    with path.open("r+b") as handle:
        handle.truncate(0)
    result["rotated"] = True
    result["archive_path"] = str(archive_path)
    result["size_after"] = path.stat().st_size
    return result


def rotate_logs(paths: list[Path] | None = None) -> dict[str, Any]:
    targets = paths or LOG_TARGETS
    items = [rotate_log_file(path) for path in targets]
    return {
        "count": len(items),
        "rotated": sum(1 for item in items if item.get("rotated")),
        "items": items,
    }


def _load_session_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _session_entry_matches(entry: Any, session_path: Path) -> bool:
    if not isinstance(entry, dict):
        return False
    session_file = entry.get("sessionFile")
    if session_file:
        try:
            if Path(str(session_file)).resolve() == session_path.resolve():
                return True
        except Exception:
            if str(session_file) == str(session_path):
                return True
    session_id = str(entry.get("sessionId") or "").strip()
    return bool(session_id) and session_id == session_path.stem


def _prune_session_index(index_payload: dict[str, Any], session_path: Path) -> list[str]:
    removed_keys: list[str] = []
    for key, value in list(index_payload.items()):
        if _session_entry_matches(value, session_path):
            index_payload.pop(key, None)
            removed_keys.append(key)
    return removed_keys


def archive_agent_sessions(
    *,
    agents_root: Path = AGENTS_ROOT,
    archive_root: Path = AGENT_SESSION_ARCHIVE_ROOT,
    hot_days: int = SESSION_ARCHIVE_AFTER_DAYS,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=hot_days)
    items: list[dict[str, Any]] = []
    session_index_cache: dict[Path, dict[str, Any]] = {}
    session_indexes_dirty: set[Path] = set()
    if not agents_root.exists():
        return {"count": 0, "archived": 0, "items": items}
    for path in sorted(agents_root.glob("*/sessions/*.jsonl")):
        if path.name == "sessions.json":
            continue
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
        archived = False
        archive_path: Path | None = None
        removed_index_entries: list[str] = []
        if modified_at < cutoff:
            agent_id = path.parent.parent.name
            archive_path = archive_root / agent_id / modified_at.strftime("%Y-%m") / f"{path.name}.gz"
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            if not archive_path.exists():
                with path.open("rb") as source_handle, gzip.open(archive_path, "wb") as archive_handle:
                    shutil.copyfileobj(source_handle, archive_handle)
            session_index_path = path.parent / "sessions.json"
            index_payload = session_index_cache.setdefault(session_index_path, _load_session_index(session_index_path))
            removed_index_entries = _prune_session_index(index_payload, path)
            if removed_index_entries:
                session_indexes_dirty.add(session_index_path)
            path.unlink()
            archived = True
        items.append(
            {
                "path": str(path),
                "modified_at": modified_at.isoformat(),
                "archived": archived,
                "archive_path": str(archive_path) if archive_path else None,
                "removed_index_entries": removed_index_entries,
            }
        )
    for index_path in session_indexes_dirty:
        payload = session_index_cache.get(index_path, {})
        index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "count": len(items),
        "archived": sum(1 for item in items if item["archived"]),
        "items": items,
    }


def split_monthly_jsonl(
    path: Path,
    *,
    archive_root: Path = REPORT_ARCHIVE_ROOT,
    timestamp_keys: tuple[str, ...],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    current_month = _month_key(now)
    result = {
        "path": str(path),
        "exists": path.exists(),
        "kept_lines": 0,
        "archived_lines": 0,
        "archives": {},
    }
    if not path.exists():
        return result
    keep_lines: list[str] = []
    archived_by_month: dict[str, list[str]] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            keep_lines.append(line)
            continue
        parsed_at = None
        for key in timestamp_keys:
            parsed_at = _parse_iso_datetime(payload.get(key))
            if parsed_at is not None:
                break
        if parsed_at is None:
            keep_lines.append(line)
            continue
        month = _month_key(parsed_at)
        if month == current_month:
            keep_lines.append(line)
            continue
        archived_by_month.setdefault(month, []).append(line)
    for month, lines in archived_by_month.items():
        archive_path = archive_root / f"{path.stem}-{month}.jsonl.gz"
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(archive_path, "at", encoding="utf-8") as handle:
            for line in lines:
                handle.write(line + "\n")
        result["archives"][month] = {
            "path": str(archive_path),
            "count": len(lines),
        }
    path.write_text("".join(f"{line}\n" for line in keep_lines), encoding="utf-8")
    result["kept_lines"] = len(keep_lines)
    result["archived_lines"] = sum(len(lines) for lines in archived_by_month.values())
    return result


def split_strategy_jsonl_monthly(*, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    items = {
        name: split_monthly_jsonl(path, archive_root=REPORT_ARCHIVE_ROOT, timestamp_keys=timestamp_keys, now=now)
        for name, (path, timestamp_keys) in MONTHLY_JSONL_TARGETS.items()
    }
    return {
        "count": len(items),
        "archived_lines": sum(item["archived_lines"] for item in items.values()),
        "items": items,
    }


def _ensure_archive_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.executescript(SCHEMA)
    connection.commit()
    return connection


def archive_db_tables(
    *,
    db_path: Path = DB_PATH,
    archive_root: Path = DB_ARCHIVE_ROOT,
    retention_days: dict[str, int] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    retention_days = retention_days or DB_RETENTION_DAYS
    result_items: list[dict[str, Any]] = []
    if not db_path.exists():
        return {"vacuumed": False, "archived_rows": 0, "items": result_items}
    archive_connections: dict[str, sqlite3.Connection] = {}
    vacuum_needed = False
    with sqlite3.connect(db_path) as main_conn:
        main_conn.row_factory = sqlite3.Row
        for table, days in retention_days.items():
            cutoff = (now - timedelta(days=days)).astimezone(UTC).isoformat()
            rows = main_conn.execute(
                f"SELECT rowid AS _rowid, * FROM {table} WHERE created_at < ? ORDER BY created_at ASC",
                (cutoff,),
            ).fetchall()
            archived_count = 0
            deleted_rowids: list[int] = []
            if rows:
                columns = [row["name"] for row in main_conn.execute(f"PRAGMA table_info({table})").fetchall()]
                placeholders = ", ".join("?" for _ in columns)
                column_list = ", ".join(columns)
                for row in rows:
                    created_at = _parse_iso_datetime(row["created_at"])
                    if created_at is None:
                        continue
                    month = _month_key(created_at)
                    archive_db_path = archive_root / f"trader-archive-{month}.db"
                    if month not in archive_connections:
                        archive_connections[month] = _ensure_archive_db(archive_db_path)
                    archive_conn = archive_connections[month]
                    values = [row[column] for column in columns]
                    archive_conn.execute(
                        f"INSERT OR REPLACE INTO {table} ({column_list}) VALUES ({placeholders})",
                        values,
                    )
                    deleted_rowids.append(int(row["_rowid"]))
                    archived_count += 1
                if archived_count:
                    vacuum_needed = True
                    for month in { _month_key(_parse_iso_datetime(row["created_at"]) or now) for row in rows }:
                        archive_connections[month].commit()
                    for index in range(0, len(deleted_rowids), 500):
                        chunk = deleted_rowids[index : index + 500]
                        sql = f"DELETE FROM {table} WHERE rowid IN ({', '.join('?' for _ in chunk)})"
                        main_conn.execute(sql, chunk)
                    main_conn.commit()
            result_items.append(
                {
                    "table": table,
                    "retention_days": days,
                    "archived_rows": archived_count,
                }
            )
        if vacuum_needed:
            main_conn.execute("VACUUM")
    for connection in archive_connections.values():
        connection.close()
    return {
        "vacuumed": vacuum_needed,
        "archived_rows": sum(item["archived_rows"] for item in result_items),
        "items": result_items,
    }


def run_maintenance(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    sessions_result: dict[str, Any]
    if SESSION_ARCHIVE_ENABLED:
        sessions_result = archive_agent_sessions(now=now)
    else:
        sessions_result = {
            "enabled": False,
            "skipped": True,
            "reason": "session_archival_disabled",
            "count": 0,
            "archived": 0,
            "items": [],
        }
    return {
        "generated_at": now.astimezone(UTC).isoformat(),
        "logs": rotate_logs(),
        "sessions": sessions_result,
        "strategy_jsonl": split_strategy_jsonl_monthly(now=now),
        "state_db": archive_db_tables(now=now),
    }
