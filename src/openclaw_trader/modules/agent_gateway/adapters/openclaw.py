from __future__ import annotations

import json
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from json import JSONDecodeError, JSONDecoder
from pathlib import Path
from typing import Any

from ...agent_gateway.models import AgentReply, AgentTask

_TASK_HINTS: dict[str, set[str]] = {
    "strategy": {
        "portfolio_mode",
        "target_gross_exposure_band_pct",
        "portfolio_thesis",
        "portfolio_invalidation",
        "change_summary",
        "targets",
        "scheduled_rechecks",
    },
    "execution": {
        "decision_id",
        "strategy_id",
        "generated_at_utc",
        "trigger_type",
        "decisions",
    },
    "news": {
        "events",
    },
    "retro": {
        "owner_summary",
        "reset_command",
        "learning_completed",
    },
    "retro_turn": {
        "speaker_role",
        "statement",
    },
}


@dataclass
class _CommandResult:
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False


class OpenClawAgentRunner:
    def __init__(self, agent_name: str, *, timeout_seconds: int = 60) -> None:
        self.agent_name = agent_name
        self.timeout_seconds = timeout_seconds

    def run(self, task: AgentTask) -> AgentReply:
        prompt = json.dumps(task.payload, ensure_ascii=False)
        session_id = task.session_id or f"{task.agent_role}-session"
        run_started_at = time.time()
        fallback_path = _workspace_fallback_path(task=task, agent_name=self.agent_name)
        previous_fallback_mtime = _path_mtime(fallback_path)
        command = [
            "openclaw",
            "agent",
            "--agent",
            self.agent_name,
            "--session-id",
            session_id,
            "--message",
            prompt,
            "--json",
            "--timeout",
            str(self.timeout_seconds),
        ]
        completed = _run_command(command, timeout_seconds=self.timeout_seconds + 5)
        if completed.timed_out:
            fallback_payload = _load_workspace_fallback(
                task=task,
                fallback_path=fallback_path,
                previous_mtime=previous_fallback_mtime,
                run_started_at=run_started_at,
            )
            if fallback_payload is not None:
                return AgentReply(
                    task_id=task.task_id,
                    agent_role=task.agent_role,
                    status="completed",
                    payload=fallback_payload,
                    meta={
                        "error_kind": "agent_timeout",
                        "fallback_payload_used": True,
                        "fallback_payload_path": str(fallback_path),
                        "session_id": session_id,
                        "command": command,
                        "stdout": completed.stdout,
                        "stderr": completed.stderr,
                    },
                )
            return AgentReply(
                task_id=task.task_id,
                agent_role=task.agent_role,
                status="needs_escalation",
                meta={
                    "error_kind": "agent_timeout",
                    "session_id": session_id,
                    "command": command,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                },
            )

        stdout = completed.stdout
        stderr = completed.stderr
        envelope = _extract_last_json_value(stdout)
        meta = {
            "session_id": session_id,
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": completed.returncode,
            "envelope": envelope,
        }
        if completed.returncode != 0:
            fallback_payload = _load_workspace_fallback(
                task=task,
                fallback_path=fallback_path,
                previous_mtime=previous_fallback_mtime,
                run_started_at=run_started_at,
            )
            if fallback_payload is not None:
                return AgentReply(
                    task_id=task.task_id,
                    agent_role=task.agent_role,
                    status="completed",
                    payload=fallback_payload,
                    meta={**meta, "error_kind": "agent_process_failed", "fallback_payload_used": True, "fallback_payload_path": str(fallback_path)},
                )
            return AgentReply(
                task_id=task.task_id,
                agent_role=task.agent_role,
                status="needs_escalation",
                meta={**meta, "error_kind": "agent_process_failed"},
            )

        payload = _extract_best_payload(envelope, task.task_kind)
        if payload is None:
            payload = _extract_best_payload(stdout, task.task_kind)
        if payload is None:
            fallback_payload = _load_workspace_fallback(
                task=task,
                fallback_path=fallback_path,
                previous_mtime=previous_fallback_mtime,
                run_started_at=run_started_at,
            )
            if fallback_payload is not None:
                return AgentReply(
                    task_id=task.task_id,
                    agent_role=task.agent_role,
                    status="completed",
                    payload=fallback_payload,
                    meta={**meta, "error_kind": "agent_invalid_transport_payload", "fallback_payload_used": True, "fallback_payload_path": str(fallback_path)},
                )
            return AgentReply(
                task_id=task.task_id,
                agent_role=task.agent_role,
                status="needs_revision",
                meta={**meta, "error_kind": "agent_invalid_transport_payload"},
            )
        return AgentReply(
            task_id=task.task_id,
            agent_role=task.agent_role,
            status="completed",
            payload=payload,
            meta=meta,
        )


class OpenClawSessionController:
    def __init__(self, agent_name_by_role: dict[str, str], *, timeout_seconds: int = 60) -> None:
        self.agent_name_by_role = dict(agent_name_by_role)
        self.timeout_seconds = timeout_seconds

    def reset(self, *, agent_role: str, session_id: str, reset_command: str = "/new") -> dict[str, object]:
        agent_name = self.agent_name_by_role.get(agent_role, agent_role)
        completed = _run_command(
            [
                "openclaw",
                "agent",
                "--agent",
                agent_name,
                "--session-id",
                session_id,
                "--message",
                reset_command,
                "--json",
                "--timeout",
                str(self.timeout_seconds),
            ],
            timeout_seconds=self.timeout_seconds + 5,
        )
        payload = _extract_last_json_value(completed.stdout)
        effective_session_id = session_id
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, dict):
                meta = result.get("meta")
                if isinstance(meta, dict):
                    agent_meta = meta.get("agentMeta")
                    if isinstance(agent_meta, dict):
                        effective_session_id = str(agent_meta.get("sessionId") or effective_session_id)
                    report = meta.get("systemPromptReport")
                    if isinstance(report, dict):
                        effective_session_id = str(report.get("sessionId") or effective_session_id)
        return {
            "agent_role": agent_role,
            "session_id": session_id,
            "effective_session_id": effective_session_id,
            "reset_command": reset_command,
            "success": completed.returncode == 0 and not completed.timed_out,
            "payload": payload if isinstance(payload, dict) else {"raw": completed.stdout},
            "error": completed.stderr or None,
        }


def _run_command(command: list[str], *, timeout_seconds: int) -> _CommandResult:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        return _CommandResult(
            returncode=process.returncode or 0,
            stdout=(stdout or "").strip(),
            stderr=(stderr or "").strip(),
        )
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
        return _CommandResult(
            returncode=process.returncode or -1,
            stdout=(stdout or "").strip(),
            stderr=(stderr or "").strip(),
            timed_out=True,
        )


def _extract_last_json_value(text: str) -> Any | None:
    decoder = JSONDecoder()
    values: list[Any] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char not in "{[":
            index += 1
            continue
        try:
            value, end = decoder.raw_decode(text, index)
        except JSONDecodeError:
            index += 1
            continue
        values.append(value)
        index = end
    return values[-1] if values else None


def _extract_best_payload(source: Any, task_kind: str) -> dict[str, Any] | None:
    hints = _TASK_HINTS.get(task_kind, set())
    priority_candidates = _collect_priority_candidates(source)
    best_payload = _pick_best_candidate(priority_candidates, hints)
    if best_payload is not None:
        return best_payload
    candidates = _collect_dict_candidates(source)
    best_payload = _pick_best_candidate(candidates, hints)
    if best_payload is not None:
        return best_payload
    if isinstance(source, dict) and source:
        return source
    return None


def _pick_best_candidate(candidates: list[dict[str, Any]], hints: set[str]) -> dict[str, Any] | None:
    best_score: tuple[int, int] = (-1, 0)
    best_payload: dict[str, Any] | None = None
    for candidate in candidates:
        score = (len(hints.intersection(candidate.keys())), -len(candidate.keys()))
        if score > best_score:
            best_score = score
            best_payload = candidate
    return best_payload


def _collect_priority_candidates(source: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if not isinstance(source, dict):
        return candidates

    def visit_text_container(value: Any) -> None:
        parsed = _extract_json_from_string(value) if isinstance(value, str) else value
        if isinstance(parsed, dict):
            candidates.extend(_collect_dict_candidates(parsed))
        elif isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    candidates.extend(_collect_dict_candidates(item))

    final = source.get("final")
    if isinstance(final, dict):
        visit_text_container(final.get("content"))

    result = source.get("result")
    if isinstance(result, dict):
        payloads = result.get("payloads")
        if isinstance(payloads, list):
            for item in payloads:
                if isinstance(item, dict):
                    visit_text_container(item.get("text"))
                    visit_text_container(item.get("content"))
                    visit_text_container(item.get("payload"))

    payloads = source.get("payloads")
    if isinstance(payloads, list):
        for item in payloads:
            if isinstance(item, dict):
                visit_text_container(item.get("text"))
                visit_text_container(item.get("content"))
                visit_text_container(item.get("payload"))

    return candidates


def _collect_dict_candidates(source: Any) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            candidates.append(value)
            for nested in value.values():
                visit(nested)
            return
        if isinstance(value, list):
            for nested in value:
                visit(nested)
            return
        if isinstance(value, str):
            parsed = _extract_json_from_string(value)
            if parsed is not None:
                visit(parsed)

    visit(source)
    return candidates


def _extract_json_from_string(value: str) -> Any | None:
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
            stripped = "\n".join(lines[1:-1]).strip()
    try:
        return json.loads(stripped)
    except JSONDecodeError:
        return _extract_last_json_value(stripped)


def _workspace_fallback_path(*, task: AgentTask, agent_name: str) -> Path | None:
    if task.agent_role != "risk_trader" or task.task_kind != "execution":
        return None
    return Path.home() / ".openclaw" / f"workspace-{agent_name}" / "execution_submission.json"


def _path_mtime(path: Path | None) -> float | None:
    if path is None or not path.exists():
        return None
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _load_workspace_fallback(
    *,
    task: AgentTask,
    fallback_path: Path | None,
    previous_mtime: float | None,
    run_started_at: float,
) -> dict[str, Any] | None:
    if task.agent_role != "risk_trader" or fallback_path is None or not fallback_path.exists():
        return None
    current_mtime = _path_mtime(fallback_path)
    if current_mtime is None:
        return None
    if previous_mtime is not None and current_mtime <= previous_mtime:
        return None
    if current_mtime < run_started_at - 1.0:
        return None
    try:
        raw = fallback_path.read_text()
    except OSError:
        return None
    parsed = _extract_json_from_string(raw)
    return parsed if isinstance(parsed, dict) else None
