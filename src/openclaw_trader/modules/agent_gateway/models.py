from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class AgentRuntimeInput(BaseModel):
    input_id: str
    agent_role: str
    task_kind: str
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentRuntimePack(BaseModel):
    input_id: str
    trace_id: str
    agent_role: str
    task_kind: str
    trigger_type: str
    expires_at_utc: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentRuntimeLease(BaseModel):
    pack: AgentRuntimePack
    status: str = "issued"
    issued_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    consumed_at_utc: datetime | None = None
    trigger_context: dict[str, Any] = Field(default_factory=dict)
    hidden_payload: dict[str, Any] = Field(default_factory=dict)


class AgentTask(BaseModel):
    task_id: str
    agent_role: str
    task_kind: str
    input_id: str
    trace_id: str
    session_id: str | None = None
    reply_contract: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AgentReply(BaseModel):
    task_id: str
    agent_role: str
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    meta: dict[str, Any] = Field(default_factory=dict)
    returned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentEscalation(BaseModel):
    escalation_id: str
    task_id: str
    agent_role: str
    reason: str
    requested_owner_decision: bool = False


class RetroTranscriptEntry(BaseModel):
    round_index: int
    speaker_role: str
    statement: str
    recorded_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RetroMeetingTurn(BaseModel):
    meeting_id: str
    round_index: int
    speaker_role: str
    transcript: list[RetroTranscriptEntry] = Field(default_factory=list)
    runtime_input_ref: str
    transcript_seen_count: int = 0
    transcript_total_count: int = 0
    runtime_input_included: bool = True


class RetroTurnReply(BaseModel):
    speaker_role: str
    statement: str


class RetroLearningAck(BaseModel):
    agent_role: str
    learning_updated: bool
    learning_path: str
    learning_summary: str


class RetroMeetingResult(BaseModel):
    meeting_id: str
    round_count: int
    transcript: list[RetroTranscriptEntry] = Field(default_factory=list)
    learning_results: list[RetroLearningAck] = Field(default_factory=list)
    owner_summary: str
    reset_command: str = "/new"
    learning_completed: bool = False


class RetroSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_summary: str
    reset_command: str = "/new"
    learning_completed: bool = False
    learning_results: Any = Field(default_factory=list)
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    round_count: int | None = None
    meeting_id: str | None = None


class StrategySubmissionTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    state: str
    direction: str
    target_exposure_band_pct: list[float] = Field(default_factory=list)
    rt_discretion_band_pct: float = 0.0
    priority: int = 1


class StrategyScheduledRecheck(BaseModel):
    recheck_at_utc: datetime
    scope: str
    reason: str


class StrategySubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolio_mode: str
    target_gross_exposure_band_pct: list[float] = Field(default_factory=list)
    portfolio_thesis: str
    portfolio_invalidation: str
    change_summary: str
    targets: list[StrategySubmissionTarget] = Field(default_factory=list)
    scheduled_rechecks: list[StrategyScheduledRecheck] = Field(default_factory=list)


class ExecutionSubmissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    action: Literal["open", "add", "reduce", "close", "flip", "wait", "hold"]
    direction: Literal["long", "short", "flat"] | None = None
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
    urgency: Literal["low", "normal", "high"]
    valid_for_minutes: int


class TacticalMapCoinUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coin: str
    working_posture: str
    base_case: str
    preferred_add_condition: str
    preferred_reduce_condition: str
    reference_take_profit_condition: str | None = None
    reference_stop_loss_condition: str | None = None
    no_trade_zone: str
    force_pm_recheck_condition: str
    next_focus: str


class TacticalMapUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map_refresh_reason: str
    portfolio_posture: str
    desk_focus: str
    risk_bias: str
    next_review_hint: str | None = None
    coins: list[TacticalMapCoinUpdate] = Field(default_factory=list)


class ExecutionSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: str
    strategy_id: str | None = None
    generated_at_utc: datetime
    trigger_type: str
    decisions: list[ExecutionSubmissionDecision]
    tactical_map_update: TacticalMapUpdate | None = None


class NewsSubmissionEvent(BaseModel):
    event_id: str
    category: str
    summary: str
    impact_level: str


class NewsSubmission(BaseModel):
    events: list[NewsSubmissionEvent] = Field(default_factory=list)


class DirectAgentReminder(BaseModel):
    reminder_id: str
    from_agent_role: str
    to_agent_role: str
    importance: str
    message: str


class ValidatedSubmissionEnvelope(BaseModel):
    envelope_id: str
    submission_kind: str
    trace_id: str
    agent_role: str
    schema_ref: str
    prompt_ref: str
    payload: dict[str, Any] = Field(default_factory=dict)
    validated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
