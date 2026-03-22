from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class WorkflowStateRef(BaseModel):
    workflow_id: str
    trace_id: str
    state: str
    reason: str
    last_transition_at: datetime


class PortfolioState(BaseModel):
    trace_id: str
    positions: list[dict[str, Any]] = Field(default_factory=list)
    total_equity_usd: str = "0"
    available_equity_usd: str = "0"
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StateSnapshot(BaseModel):
    snapshot_id: str
    trace_id: str
    workflow_state: WorkflowStateRef | None = None
    portfolio_state: PortfolioState | None = None
    strategy_ref: str | None = None
    captured_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MemoryView(BaseModel):
    memory_id: str
    scope: str
    decision_refs: list[str] = Field(default_factory=list)
    learning_refs: list[str] = Field(default_factory=list)
    summary: str


class NotificationResult(BaseModel):
    notification_id: str
    delivered: bool
    provider_message_id: str | None = None
    failure_reason: str | None = None
    delivered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReplayQueryView(BaseModel):
    trace_id: str | None = None
    time_window: dict[str, str | None] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)
    states: list[dict[str, Any]] = Field(default_factory=list)
    render_hints: dict[str, Any] = Field(default_factory=dict)


class StrategyTargetAsset(BaseModel):
    symbol: str
    state: str
    direction: str
    target_exposure_band_pct: list[float] = Field(default_factory=list)
    rt_discretion_band_pct: float = 0.0
    no_new_risk: bool = False
    priority: int = 1


class ScheduledRecheck(BaseModel):
    recheck_at_utc: datetime
    scope: str
    reason: str


class StrategyAsset(BaseModel):
    strategy_id: str
    strategy_day_utc: str
    generated_at_utc: datetime
    trigger_type: str
    supersedes_strategy_id: str | None = None
    revision_number: int = 1
    portfolio_mode: str
    target_gross_exposure_band_pct: list[float] = Field(default_factory=list)
    portfolio_thesis: str
    portfolio_invalidation: str
    change_summary: str
    targets: list[StrategyTargetAsset] = Field(default_factory=list)
    scheduled_rechecks: list[ScheduledRecheck] = Field(default_factory=list)


class ExecutionDecisionRecord(BaseModel):
    symbol: str
    action: str
    direction: str | None = None
    reason: str
    size_pct_of_equity: float | None = None
    priority: int
    urgency: str
    valid_for_minutes: int
    escalate_to_pm: bool
    escalation_reason: str | None = None


class ExecutionBatch(BaseModel):
    decision_id: str
    strategy_id: str | None = None
    generated_at_utc: datetime
    trigger_type: str
    decisions: list[ExecutionDecisionRecord] = Field(default_factory=list)


class ExecutionResultRecord(BaseModel):
    result_id: str
    plan_id: str
    decision_id: str
    strategy_id: str | None = None
    symbol: str
    action: str
    side: str
    notional_usd: str | None = None
    success: bool
    exchange_order_id: str | None = None
    message: str | None = None
    fills: list[dict[str, Any]] = Field(default_factory=list)
    executed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    technical_failure: bool = False


class MacroEventRecord(BaseModel):
    event_id: str
    category: str
    summary: str
    impact_level: str
    source_refs: list[str] = Field(default_factory=list)
    generated_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))


class NewsSubmissionEventAsset(BaseModel):
    event_id: str
    category: str
    summary: str
    impact_level: str


class NewsSubmissionAsset(BaseModel):
    submission_id: str
    generated_at_utc: datetime
    events: list[NewsSubmissionEventAsset] = Field(default_factory=list)


class MacroDailyMemory(BaseModel):
    memory_day_utc: str
    summary: str
    event_ids: list[str] = Field(default_factory=list)
    updated_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))


class MemoryProjection(BaseModel):
    projection_id: str
    memory_scope: str
    source_ref: str
    projection_text: str
    synced_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentSessionState(BaseModel):
    agent_role: str
    session_id: str
    status: str = "active"
    last_task_kind: str | None = None
    last_submission_kind: str | None = None
    last_reset_command: str | None = None
    last_active_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AssetRecord(BaseModel):
    asset_id: str
    asset_type: str
    trace_id: str | None = None
    actor_role: str | None = None
    group_key: str | None = None
    source_ref: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class OverviewQueryView(BaseModel):
    system: dict[str, Any] = Field(default_factory=dict)
    latest_strategy: dict[str, Any] | None = None
    latest_portfolio: dict[str, Any] | None = None
    portfolio_history: list[dict[str, Any]] = Field(default_factory=list)
    latest_execution_batch: dict[str, Any] | None = None
    recent_execution_results: list[dict[str, Any]] = Field(default_factory=list)
    current_macro_events: list[dict[str, Any]] = Field(default_factory=list)
    agent_sessions: list[dict[str, Any]] = Field(default_factory=list)
    recent_notifications: list[dict[str, Any]] = Field(default_factory=list)
    recent_events: list[dict[str, Any]] = Field(default_factory=list)
