from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class CommandType(str, Enum):
    refresh_strategy = "refresh_strategy"
    rerun_trade_review = "rerun_trade_review"
    dispatch_once = "dispatch_once"
    run_pm = "run_pm"
    run_rt = "run_rt"
    run_mea = "run_mea"
    run_retro_prep = "run_retro_prep"
    reset_agent_sessions = "reset_agent_sessions"
    sync_news = "sync_news"
    emit_daily_report = "emit_daily_report"
    retrain_models = "retrain_models"
    replay_window = "replay_window"
    pause_workflow = "pause_workflow"
    resume_workflow = "resume_workflow"


class ManualTriggerCommand(BaseModel):
    command_id: str
    command_type: CommandType
    initiator: str
    scope: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkflowCommandReceipt(BaseModel):
    command_id: str
    accepted: bool
    reason: str
    workflow_id: str | None = None
    trace_id: str | None = None
    received_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class WorkflowStateRecord(BaseModel):
    workflow_id: str
    trace_id: str
    state: str
    reason: str
    last_transition_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload_ref: str | None = None


class ExternalCadenceWakeup(BaseModel):
    agent_role: str
    scheduled_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    delivered_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: str = "openclaw_cron"
    cadence_label: str
