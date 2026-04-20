from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


EvidenceType = Literal["price_action", "quant_forecast", "narrative", "regime", "mixed"]


class StrategyThesisClaim(BaseModel):
    """Single thesis statement with an evidence tag (spec 015 FR-001)."""

    model_config = ConfigDict(extra="forbid")

    statement: str = Field(min_length=1)
    evidence_type: EvidenceType
    evidence_sources: list[str] = Field(default_factory=list)


class StrategyEvidenceBreakdown(BaseModel):
    """Summed-to-100 split across evidence types (spec 015 FR-002)."""

    model_config = ConfigDict(extra="forbid")

    price_action_pct: float = Field(ge=0.0, le=100.0)
    quant_forecast_pct: float = Field(ge=0.0, le=100.0)
    narrative_pct: float = Field(ge=0.0, le=100.0)
    regime_pct: float = Field(ge=0.0, le=100.0)

    @model_validator(mode="after")
    def _sum_must_be_100(self) -> "StrategyEvidenceBreakdown":
        total = (
            self.price_action_pct
            + self.quant_forecast_pct
            + self.narrative_pct
            + self.regime_pct
        )
        if abs(total - 100.0) > 0.01:
            raise ValueError(
                f"evidence_breakdown must sum to 100.0, got {total:.2f}"
            )
        return self


class StrategyChangeSummary(BaseModel):
    """Structured change summary (spec 015 FR-002 / FR-006)."""

    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=1)
    evidence_breakdown: StrategyEvidenceBreakdown
    why_no_external_trigger: str | None = None


def _coerce_thesis_claims(value: Any) -> Any:
    """Back-compat: accept a plain string thesis; coerce to one 'mixed' claim.

    Preserves the ~47 legacy string fixtures in tests and any pre-015 strategy
    assets. New submissions through the PM skill return structured arrays.
    """
    if isinstance(value, str):
        statement = value.strip()
        if not statement:
            return value  # fall through to field validator; raises
        return [
            {
                "statement": statement,
                "evidence_type": "mixed",
                "evidence_sources": [],
            }
        ]
    return value


def _coerce_change_summary(value: Any) -> Any:
    """Back-compat: accept a plain string change_summary; coerce to structured."""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        return {
            "headline": text,
            "evidence_breakdown": {
                "price_action_pct": 25.0,
                "quant_forecast_pct": 25.0,
                "narrative_pct": 25.0,
                "regime_pct": 25.0,
            },
            "why_no_external_trigger": None,
        }
    return value


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


class RetroLearningAck(BaseModel):
    agent_role: str
    learning_updated: bool
    learning_path: str
    learning_summary: str


class RetroSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_summary: str
    case_id: str | None = None
    reset_command: str = "/new"
    learning_completed: bool = False
    learning_results: Any = Field(default_factory=list)
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    round_count: int | None = None
    meeting_id: str | None = None
    root_cause_ranking: list[str] = Field(default_factory=list)
    role_judgements: dict[str, str] = Field(default_factory=dict)
    learning_directives: list[dict[str, Any]] = Field(default_factory=list)


class RetroBriefSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str | None = None
    root_cause: str
    cross_role_challenge: str
    self_critique: str
    tomorrow_change: str


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
    portfolio_thesis: list[StrategyThesisClaim] = Field(min_length=1)
    portfolio_invalidation: str
    flip_triggers: str
    change_summary: StrategyChangeSummary
    targets: list[StrategySubmissionTarget] = Field(default_factory=list)
    scheduled_rechecks: list[StrategyScheduledRecheck] = Field(default_factory=list)

    @field_validator("portfolio_thesis", mode="before")
    @classmethod
    def _coerce_legacy_thesis(cls, value: Any) -> Any:
        return _coerce_thesis_claims(value)

    @field_validator("change_summary", mode="before")
    @classmethod
    def _coerce_legacy_change_summary(cls, value: Any) -> Any:
        return _coerce_change_summary(value)

    @model_validator(mode="after")
    def _validate_thesis_evidence_variety(self) -> "StrategySubmission":
        # Spec 015 scenario 1 verification: at least two distinct evidence_types
        # per submission — but only enforce when there are ≥ 2 claims, so the
        # legacy single-string coercion still passes while production PM output
        # (3+ claims) is held to the discipline.
        if len(self.portfolio_thesis) < 2:
            return self
        distinct_types = {claim.evidence_type for claim in self.portfolio_thesis}
        if len(distinct_types) < 2:
            raise ValueError(
                "portfolio_thesis must cover at least two distinct evidence_types "
                "when you list multiple claims"
            )
        return self

    @model_validator(mode="after")
    def _validate_targets_cover_supported_symbols(self) -> "StrategySubmission":
        symbols = [str(item.symbol or "").strip().upper() for item in self.targets]
        expected = {"BTC", "ETH"}
        actual = set(symbols)
        missing = sorted(expected - actual)
        extras = sorted(actual - expected)
        duplicates = sorted({symbol for symbol in symbols if symbol and symbols.count(symbol) > 1})
        if missing or extras or duplicates or len(self.targets) != 2:
            problems: list[str] = []
            if missing:
                problems.append(f"missing targets for {', '.join(missing)}")
            if extras:
                problems.append(f"unsupported target symbols {', '.join(extras)}")
            if duplicates:
                problems.append(f"duplicate target symbols {', '.join(duplicates)}")
            if len(self.targets) != 2:
                problems.append("targets must contain exactly 2 entries (BTC, ETH)")
            raise ValueError("; ".join(problems))
        return self


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
    first_entry_plan: str = Field(min_length=1)
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
    pm_recheck_requested: bool = False
    pm_recheck_reason: str | None = None
    tactical_map_update: TacticalMapUpdate | None = None

    @model_validator(mode="after")
    def _validate_pm_recheck_fields(self) -> "ExecutionSubmission":
        if self.pm_recheck_requested and not str(self.pm_recheck_reason or "").strip():
            raise ValueError("pm_recheck_reason is required when pm_recheck_requested=true")
        return self


class NewsSubmissionEvent(BaseModel):
    event_id: str
    category: str
    summary: str
    impact_level: str
    thesis_alignment: Literal["reinforces", "weakens", "flip_trigger", "neutral"] | None = None


class NewsSubmission(BaseModel):
    events: list[NewsSubmissionEvent] = Field(default_factory=list)


class MacroBriefRegimeTagsSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    usd_trend: str | None = None
    real_rates: str | None = None
    crypto_carry_btc: str | None = None
    crypto_carry_eth: str | None = None
    crypto_iv_regime: str | None = None
    btc_positioning: str | None = None
    eth_positioning: str | None = None
    fed_next_meeting_skew: str | None = None
    sentiment_bucket: str | None = None
    regime_summary: str | None = None


class MacroBriefPriorReviewSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prior_brief_id: str | None = None
    verdict: Literal["validated", "partially_validated", "falsified", "no_prior"] = "no_prior"
    notes: str | None = None


class MacroBriefSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid_until_utc: datetime
    wake_mode: Literal["daily_macro_brief", "event_driven_macro_brief"] = "daily_macro_brief"
    regime_tags: MacroBriefRegimeTagsSubmission = Field(default_factory=MacroBriefRegimeTagsSubmission)
    narrative: str = Field(min_length=1)
    pm_directives: list[str] = Field(default_factory=list)
    monitoring_triggers: list[str] = Field(default_factory=list)
    prior_brief_review: MacroBriefPriorReviewSubmission = Field(default_factory=MacroBriefPriorReviewSubmission)
    data_source_snapshot: dict[str, Any] = Field(default_factory=dict)


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
