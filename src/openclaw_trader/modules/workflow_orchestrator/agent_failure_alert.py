"""Agent LLM-failure → owner wecom alert monitor.

Background: when an agent (PM / RT / MEA / Chief) is woken by WO but its
underlying LLM call fails (provider quota exhausted, auth expired, weekly
limit hit, etc), WO has zero feedback loop today — it just keeps firing
the wake every `cooldown_minutes` (30 by default), each fire silently
fails, and the owner only finds out hours later by looking at session
files.

This monitor closes that gap. It tails `gateway.err.log`, recognises a
small set of well-known fatal LLM failure patterns, debounces per
(provider × failure_kind) for a configurable cooldown, and dispatches a
wecom owner alert via NotificationService.notify_owner_alert.

Stays in stdlib + the existing event/notification machinery — no new
dependency. Default-disabled so it doesn't fire surprise messages until
explicitly enabled in dispatch.yaml.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Any

from ...shared.utils import new_id
from ..memory_assets.service import MemoryAssetsService
from ..notification_service.service import NotificationService


_TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{2}:\d{2})")
_MODEL_RE = re.compile(r"model=([\w./-]+)")
_PROVIDER_RE = re.compile(r"provider=([\w-]+)")


@dataclass(frozen=True)
class _FailurePattern:
    kind: str          # short stable identifier used for cooldown keys
    needle: str        # case-insensitive substring search
    label: str         # human-readable Chinese label for the alert body


# Order matters: first match wins.
_PATTERNS: tuple[_FailurePattern, ...] = (
    _FailurePattern(
        kind="openai_oauth_weekly_limit",
        needle="ChatGPT usage limit",
        label="ChatGPT Plus 周限额触顶（OAuth）",
    ),
    _FailurePattern(
        kind="bailian_month_quota",
        needle="month allocated quota exceeded",
        label="bailian 月度额度耗尽",
    ),
    _FailurePattern(
        kind="oauth_expired",
        needle="OAuth token expired",
        label="OAuth token 过期",
    ),
    _FailurePattern(
        kind="auth_failed",
        needle="auth failed",
        label="auth 失败（可能 token 损坏）",
    ),
)


@dataclass(frozen=True)
class AgentFailureAlertConfig:
    enabled: bool = False
    scan_interval_seconds: int = 60
    cooldown_minutes: int = 60
    log_path: str = "~/.openclaw/logs/gateway.err.log"
    # Tail at most this many bytes from end on each scan — protects against
    # huge log files from blocking the scan loop.
    tail_bytes: int = 524288  # 512 KB


@dataclass
class _RecentFailure:
    kind: str
    label: str
    provider: str
    model: str
    when_iso: str
    raw_excerpt: str


@dataclass
class _AlertState:
    last_scanned_at_utc: str | None = None
    # key = "<provider>:<kind>" → last alert ISO timestamp
    last_alerts: dict[str, str] = field(default_factory=dict)


_STATE_ASSET_ID = "agent_failure_alert_state"


class AgentFailureAlertMonitor:
    def __init__(
        self,
        *,
        memory_assets: MemoryAssetsService,
        notification_service: NotificationService,
        config: AgentFailureAlertConfig | None = None,
    ) -> None:
        self.memory_assets = memory_assets
        self.notification_service = notification_service
        self.config = config or AgentFailureAlertConfig()
        self._stop = Event()
        self._thread: Thread | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> None:
        if not self.config.enabled or self._thread is not None:
            return
        self._thread = Thread(
            target=self._loop, name="workflow-orchestrator-agent-failure-alert", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception:  # noqa: BLE001
                pass
            if self._stop.wait(max(int(self.config.scan_interval_seconds), 5)):
                break

    # ------------------------------------------------------------------
    # Core scan
    # ------------------------------------------------------------------
    def scan_once(self, *, now: datetime | None = None) -> dict[str, Any]:
        current = (now or datetime.now(UTC)).astimezone(UTC)
        state = self._load_state()
        last_seen = self._parse_iso(state.last_scanned_at_utc)
        log_lines = self._tail_lines()
        new_failures: list[_RecentFailure] = []
        for line in log_lines:
            ts = self._extract_timestamp(line)
            if ts is None:
                continue
            if last_seen is not None and ts <= last_seen:
                continue
            failure = self._match_failure(line, ts)
            if failure is not None:
                new_failures.append(failure)
        # Group by (provider, kind) → keep the latest only for alert body
        latest_per_key: dict[str, _RecentFailure] = {}
        for f in new_failures:
            latest_per_key[f"{f.provider}:{f.kind}"] = f

        alerts_dispatched: list[str] = []
        for key, failure in latest_per_key.items():
            last_alert_iso = state.last_alerts.get(key)
            last_alert_dt = self._parse_iso(last_alert_iso)
            if last_alert_dt is not None:
                gap_minutes = (current - last_alert_dt).total_seconds() / 60.0
                if gap_minutes < float(self.config.cooldown_minutes):
                    continue
            self._dispatch_alert(failure)
            state.last_alerts[key] = current.isoformat()
            alerts_dispatched.append(key)

        state.last_scanned_at_utc = current.isoformat()
        self._save_state(state)
        return {
            "scanned_lines": len(log_lines),
            "new_failures": len(new_failures),
            "alerts_dispatched": alerts_dispatched,
            "now_utc": current.isoformat(),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _tail_lines(self) -> list[str]:
        path = Path(os.path.expanduser(self.config.log_path))
        if not path.exists():
            return []
        try:
            size = path.stat().st_size
            with path.open("rb") as fh:
                start = max(0, size - int(self.config.tail_bytes))
                fh.seek(start)
                # If we seeked into the middle of a line, drop the partial first line.
                blob = fh.read()
            text = blob.decode("utf-8", errors="replace")
            lines = text.splitlines()
            if start > 0 and lines:
                lines = lines[1:]
            return lines
        except OSError:
            return []

    @staticmethod
    def _extract_timestamp(line: str) -> datetime | None:
        match = _TIMESTAMP_RE.match(line)
        if not match:
            return None
        try:
            ts = datetime.fromisoformat(match.group(1))
        except ValueError:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC)

    @staticmethod
    def _match_failure(line: str, ts: datetime) -> _RecentFailure | None:
        lowered = line.lower()
        for pattern in _PATTERNS:
            if pattern.needle.lower() in lowered:
                provider_match = _PROVIDER_RE.search(line)
                # Skip lines that don't carry a provider tag — those are
                # secondary diagnostics (e.g. [compaction] summarization
                # failures) that piggyback the same error string but are not
                # the primary agent-end event. The primary `[agent/embedded]
                # embedded run agent end` line for the same root cause WILL
                # carry provider= and that's the one we want to alert on.
                if provider_match is None:
                    return None
                model_match = _MODEL_RE.search(line)
                excerpt = line.strip()
                if len(excerpt) > 280:
                    excerpt = excerpt[:280] + "…"
                return _RecentFailure(
                    kind=pattern.kind,
                    label=pattern.label,
                    provider=provider_match.group(1),
                    model=(model_match.group(1) if model_match else "unknown"),
                    when_iso=ts.isoformat(),
                    raw_excerpt=excerpt,
                )
        return None

    def _dispatch_alert(self, failure: _RecentFailure) -> None:
        body = (
            f"agent LLM 调用失败：{failure.label}\n"
            f"provider/model: {failure.provider}/{failure.model}\n"
            f"first detected: {failure.when_iso}\n"
            f"\n建议立即处置：\n"
            f"  • {self._suggested_action(failure.kind)}\n"
            f"\n日志摘录：\n{failure.raw_excerpt}"
        )
        try:
            self.notification_service.notify_owner_alert(
                trace_id=new_id("trace"),
                alert_kind=f"agent_llm_failure:{failure.kind}",
                alert_message=body,
            )
        except Exception:  # noqa: BLE001
            # Notification subsystem failure must NOT break the monitor loop.
            pass

    @staticmethod
    def _suggested_action(kind: str) -> str:
        if kind == "openai_oauth_weekly_limit":
            return (
                "OAuth 帐号 ChatGPT Plus 周限额触顶。可重登到另一个账号、"
                "升 Pro、或临时切回 bailian/qwen3.6-plus（脚本：scripts/switch_agents_to_bailian.sh）。"
            )
        if kind == "bailian_month_quota":
            return "bailian 月度额度耗尽。阿里云控制台续费，或临时切到 OAuth GPT-5.4。"
        if kind == "oauth_expired":
            return "OAuth token 过期。重跑 openclaw models --agent <id> auth login --provider openai-codex --method oauth。"
        if kind == "auth_failed":
            return "auth 失败。检查 ~/.openclaw/agents/*/agent/auth-profiles.json，必要时重登。"
        return "查看 ~/.openclaw/logs/gateway.err.log 完整堆栈定位。"

    # ------------------------------------------------------------------
    # State persistence (memory_assets asset)
    # ------------------------------------------------------------------
    def _load_state(self) -> _AlertState:
        asset = self.memory_assets.get_asset(_STATE_ASSET_ID)
        payload = dict((asset or {}).get("payload") or {})
        return _AlertState(
            last_scanned_at_utc=payload.get("last_scanned_at_utc"),
            last_alerts=dict(payload.get("last_alerts") or {}),
        )

    def _save_state(self, state: _AlertState) -> None:
        self.memory_assets.save_asset(
            asset_type="agent_failure_alert_state",
            asset_id=_STATE_ASSET_ID,
            payload={
                "last_scanned_at_utc": state.last_scanned_at_utc,
                "last_alerts": dict(state.last_alerts),
            },
            actor_role="system",
            group_key=_STATE_ASSET_ID,
        )

    @staticmethod
    def _parse_iso(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        return ts.astimezone(UTC)
