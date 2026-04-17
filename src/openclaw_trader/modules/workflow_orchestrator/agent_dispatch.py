"""Shared agent dispatch primitive used by WO monitors.

Two dispatch modes:
- send_to_session: invoke `openclaw agent --agent X --session-id Y --message Z`.
  Lands the turn in an explicit session (typically `agent:<role>:main`), so the
  agent keeps accumulating context across wakes instead of running in an isolated
  per-fire session.
- run_cron_job: invoke `openclaw cron run <job_id>` (thin wrapper over the
  existing behaviour used by PMRecheckMonitor / RetroPrepMonitor). Retained so
  scheduled-recheck / risk-brake paths that want a cold-start isolated session
  can keep using it.

Also exposes fetch_cron_job_payload_message() so rule-driven monitors can reuse
a cron job's `payload.message` as their canonical text (source of truth stays
in jobs.json; dispatch mode is moved into WO).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DispatchResult:
    ok: bool
    pid: int | None = None
    stdout: str = ""
    stderr: str = ""
    returncode: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class AgentDispatchConfig:
    openclaw_bin: str = "openclaw"
    subprocess_timeout_seconds: int = 15
    default_thinking: str = "high"
    default_turn_timeout_seconds: int = 1200


class AgentDispatcher:
    """Wraps the `openclaw` CLI for the two dispatch primitives WO needs.

    All subprocess calls are best-effort; errors are captured in DispatchResult
    rather than raised so callers (Monitor loops) can persist them to state
    without crashing their scan thread.
    """

    def __init__(self, config: AgentDispatchConfig | None = None) -> None:
        self.config = config or AgentDispatchConfig()

    # ------------------------------------------------------------------
    # Primary: land a turn in an explicit session (main session pattern)
    # ------------------------------------------------------------------
    def send_to_session(
        self,
        *,
        agent: str,
        session_key: str,
        message: str,
        thinking: str | None = None,
        turn_timeout_seconds: int | None = None,
    ) -> DispatchResult:
        """Dispatch an agent turn into `session_key` via `openclaw agent`.

        Fire-and-forget: the subprocess is spawned detached because an agent
        turn can take minutes and the Monitor scan loop runs on a 60s cadence.
        We return as soon as the CLI is confirmed to have been launched.
        """
        command = [
            self.config.openclaw_bin,
            "agent",
            "--agent",
            agent,
            "--session-id",
            session_key,
            "--message",
            message,
            "--thinking",
            (thinking or self.config.default_thinking),
            "--timeout",
            str(int(turn_timeout_seconds or self.config.default_turn_timeout_seconds)),
        ]
        try:
            process = subprocess.Popen(  # noqa: S603 - trusted CLI path
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                text=False,
            )
        except Exception as exc:  # noqa: BLE001
            return DispatchResult(ok=False, error=f"spawn_failed: {exc}")
        return DispatchResult(ok=True, pid=process.pid)

    # ------------------------------------------------------------------
    # Secondary: run an openclaw cron job (kept for scheduled_recheck /
    # risk_brake paths that want isolated-session semantics)
    # ------------------------------------------------------------------
    def run_cron_job_detached(self, *, job_id: str) -> DispatchResult:
        try:
            process = subprocess.Popen(  # noqa: S603
                [self.config.openclaw_bin, "cron", "run", job_id],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                text=False,
            )
        except Exception as exc:  # noqa: BLE001
            return DispatchResult(ok=False, error=f"spawn_failed: {exc}")
        return DispatchResult(ok=True, pid=process.pid)

    # ------------------------------------------------------------------
    # Helper: read a cron job's payload.message so rule configs can reuse
    # jobs.json as the single source of truth for dispatch text.
    # ------------------------------------------------------------------
    def fetch_cron_job_payload_message(self, *, job_id: str) -> str | None:
        payload = self._run_json([self.config.openclaw_bin, "cron", "list", "--json"])
        for job in self._iter_jobs(payload):
            if str(job.get("id") or job.get("job_id") or job.get("jobId") or "") != job_id:
                continue
            inner = job.get("payload") if isinstance(job.get("payload"), dict) else {}
            message = inner.get("message") if isinstance(inner, dict) else None
            if isinstance(message, str) and message.strip():
                return message
            return None
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _run_json(self, command: list[str]) -> Any:
        try:
            completed = subprocess.run(  # noqa: S603
                command,
                capture_output=True,
                text=True,
                timeout=int(self.config.subprocess_timeout_seconds),
                check=False,
            )
        except Exception:  # noqa: BLE001
            return None
        if completed.returncode != 0:
            return None
        for text in (completed.stdout, completed.stderr):
            if not text:
                continue
            start = text.find("{")
            if start < 0:
                start = text.find("[")
            if start < 0:
                continue
            try:
                decoder = json.JSONDecoder()
                value, _ = decoder.raw_decode(text[start:])
                return value
            except json.JSONDecodeError:
                continue
        return None

    @staticmethod
    def _iter_jobs(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("jobs", "data", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            if payload.get("id") or payload.get("job_id") or payload.get("jobId"):
                return [payload]
        return []
