from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator


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
    flip_triggers: str
    change_summary: str
    targets: list[StrategyTargetAsset] = Field(default_factory=list)
    scheduled_rechecks: list[ScheduledRecheck] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_targets_cover_supported_symbols(self) -> "StrategyAsset":
        symbols = [str(item.symbol or "").strip().upper() for item in self.targets]
        expected = {"BTC", "ETH", "SOL"}
        actual = set(symbols)
        missing = sorted(expected - actual)
        extras = sorted(actual - expected)
        duplicates = sorted({symbol for symbol in symbols if symbol and symbols.count(symbol) > 1})
        if missing or extras or duplicates or len(self.targets) != 3:
            problems: list[str] = []
            if missing:
                problems.append(f"missing targets for {', '.join(missing)}")
            if extras:
                problems.append(f"unsupported target symbols {', '.join(extras)}")
            if duplicates:
                problems.append(f"duplicate target symbols {', '.join(duplicates)}")
            if len(self.targets) != 3:
                problems.append("targets must contain exactly 3 entries (BTC, ETH, SOL)")
            raise ValueError("; ".join(problems))
        return self


class ExecutionDecisionRecord(BaseModel):
    symbol: str
    action: str
    direction: str | None = None
    reason: str
    reference_take_profit_condition: str | None = None
    reference_stop_loss_condition: str | None = None
    size_pct_of_exposure_budget: float | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "size_pct_of_exposure_budget",
            "size_pct_of_equity",
        ),
    )
    priority: int
    urgency: str
    valid_for_minutes: int


class ExecutionBatch(BaseModel):
    decision_id: str
    strategy_id: str | None = None
    generated_at_utc: datetime
    trigger_type: str
    pm_recheck_requested: bool = False
    pm_recheck_reason: str | None = None
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


class RTTacticalMapCoinAsset(BaseModel):
    coin: str
    working_posture: str
    base_case: str
    first_entry_plan: str = Field(min_length=1)
    preferred_add_condition: str
    preferred_reduce_condition: str
    reference_take_profit_condition: str | None = None
    reference_stop_loss_condition: str | None = None
    no_trade_zone: str
    force_pm_recheck_condition: str
    next_focus: str


class RTTacticalMapAsset(BaseModel):
    map_id: str
    strategy_key: str
    updated_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    refresh_reason: str
    lock_mode: str | None = None
    portfolio_posture: str
    desk_focus: str
    risk_bias: str
    next_review_hint: str | None = None
    coins: list[RTTacticalMapCoinAsset] = Field(default_factory=list)


class RuntimeBridgeState(BaseModel):
    state_id: str
    refreshed_at_utc: datetime
    refresh_reason: str
    source_timestamps: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    runtime_inputs: dict[str, Any] = Field(default_factory=dict)


class RetroCaseAsset(BaseModel):
    case_id: str
    case_day_utc: str
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    trigger_type: str
    primary_question: str
    objective_summary: str
    target_return_pct: float = 1.0
    challenge_prompts: list[str] = Field(default_factory=list)
    strategy_ids: list[str] = Field(default_factory=list)
    execution_batch_ids: list[str] = Field(default_factory=list)
    macro_event_ids: list[str] = Field(default_factory=list)
    recent_notification_ids: list[str] = Field(default_factory=list)


class RetroBriefAsset(BaseModel):
    brief_id: str
    case_id: str
    agent_role: str
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    root_cause: str
    cross_role_challenge: str
    self_critique: str
    tomorrow_change: str


class LearningDirectiveAsset(BaseModel):
    directive_id: str
    case_id: str
    agent_role: str
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_key: str
    learning_path: str
    directive: str
    rationale: str


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
    thesis_alignment: Literal["reinforces", "weakens", "flip_trigger", "neutral"] | None = None


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
    risk_overlay: dict[str, Any] | None = None
    portfolio_history: list[dict[str, Any]] = Field(default_factory=list)
    latest_execution_batch: dict[str, Any] | None = None
    recent_execution_results: list[dict[str, Any]] = Field(default_factory=list)
    current_macro_events: list[dict[str, Any]] = Field(default_factory=list)
    agent_sessions: list[dict[str, Any]] = Field(default_factory=list)
    recent_notifications: list[dict[str, Any]] = Field(default_factory=list)
    recent_events: list[dict[str, Any]] = Field(default_factory=list)
