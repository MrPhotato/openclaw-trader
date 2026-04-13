from __future__ import annotations

from dataclasses import dataclass

from ..config.loader import load_system_settings
from ..modules.agent_gateway import AgentGatewayService
from ..modules.agent_gateway.runtime_bridge import RuntimeBridgeConfig, RuntimeBridgeMonitor
from ..modules.agent_gateway.adapters import (
    DeterministicAgentRunner,
    DeterministicSessionController,
    OpenClawAgentRunner,
    OpenClawSessionController,
)
from ..modules.news_events import NewsEventService
from ..modules.news_events.adapters import DirectPollingNewsProvider
from ..modules.notification_service import NotificationService
from ..modules.notification_service.adapters import OpenClawNotificationProvider
from ..modules.policy_risk import PolicyRiskService
from ..modules.quant_intelligence import QuantIntelligenceService
from ..modules.quant_intelligence.adapters import DirectArtifactQuantProvider, DirectQuantTrainer
from ..modules.replay_frontend import ReplayFrontendService
from ..modules.memory_assets import MemoryAssetsRepository, MemoryAssetsService
from ..modules.trade_gateway.execution import ExecutionGatewayService
from ..modules.trade_gateway.execution.adapters import CoinbaseIntxBroker
from ..modules.trade_gateway.market_data import DataIngestService
from ..modules.trade_gateway.market_data.adapters import CoinbaseIntxMarketDataProvider
from ..modules.workflow_orchestrator import WorkflowOrchestratorService
from ..modules.workflow_orchestrator.pm_recheck import PMRecheckConfig, PMRecheckMonitor
from ..modules.workflow_orchestrator.retro_prep import RetroPrepConfig, RetroPrepMonitor
from ..modules.workflow_orchestrator.trigger_bridge import WorkflowTriggerBridge
from ..modules.workflow_orchestrator.handlers import WorkflowCommandExecutor
from ..modules.workflow_orchestrator.risk_brake import RiskBrakeConfig, RiskBrakeMonitor
from ..modules.workflow_orchestrator.rt_trigger import OpenClawCronRunner, RTTriggerConfig, RTTriggerMonitor
from ..shared.infra import EventBus, InMemoryEventBus, SqliteDatabase


@dataclass
class ServiceContainer:
    settings: object
    event_bus: EventBus
    memory_assets: MemoryAssetsService
    market_data: DataIngestService
    news_events: NewsEventService
    quant_intelligence: QuantIntelligenceService
    policy_risk: PolicyRiskService
    trade_execution: ExecutionGatewayService
    agent_gateway: AgentGatewayService
    notification_service: NotificationService
    replay_frontend: ReplayFrontendService
    workflow_orchestrator: WorkflowOrchestratorService
    runtime_bridge_monitor: RuntimeBridgeMonitor | None = None

    def close(self) -> None:
        self.workflow_orchestrator.close()
        if self.runtime_bridge_monitor is not None:
            self.runtime_bridge_monitor.stop()
        self.event_bus.close()


def _build_agent_runner(name: str, *, enabled: bool, timeout_seconds: int):
    if enabled:
        return OpenClawAgentRunner(name, timeout_seconds=timeout_seconds)
    return DeterministicAgentRunner()


def _agent_timeout_seconds(*, settings: object, agent_role: str) -> int:
    base_timeout = int(settings.agents.openclaw_timeout_seconds)
    if agent_role in {"risk_trader", "crypto_chief"}:
        return max(base_timeout, int(settings.orchestrator.timeout_seconds))
    return base_timeout


def _build_session_controller(*, settings: object, enabled: bool):
    if enabled:
        return OpenClawSessionController(
            {
                "pm": settings.agents.pm_agent,
                "risk_trader": settings.agents.risk_trader_agent,
                "macro_event_analyst": settings.agents.macro_event_analyst_agent,
                "crypto_chief": settings.agents.crypto_chief_agent,
            },
            timeout_seconds=max(int(settings.agents.openclaw_timeout_seconds), 300),
        )
    return DeterministicSessionController()


def build_container() -> ServiceContainer:
    settings = load_system_settings()
    event_bus = InMemoryEventBus()
    database = SqliteDatabase(settings.storage.sqlite_path)
    memory_assets = MemoryAssetsService(MemoryAssetsRepository(database))
    trigger_bridge = WorkflowTriggerBridge(memory_assets)
    memory_assets.ensure_bootstrap_parameter(
        "quant_defaults",
        "global",
        {
            "interval": settings.quant.interval,
            "history_bars": settings.quant.history_bars,
            "forecast_horizons": dict(settings.quant.forecast_horizons),
            "thresholds": {
                "min_confidence": settings.quant.min_confidence,
                "min_long_short_probability": settings.quant.min_long_short_probability,
                "meta_min_confidence": settings.quant.meta_min_confidence,
            },
            "horizon_roles": {
                "12h": "market_direction_context",
                "4h": "market_structure_context",
                "1h": "short_horizon_context",
            },
        },
        operator="system",
        reason="bootstrap_v2_quant_reference",
    )
    market_data = DataIngestService(CoinbaseIntxMarketDataProvider())
    news_events = NewsEventService(DirectPollingNewsProvider())
    quant_intelligence = QuantIntelligenceService(
        DirectArtifactQuantProvider(retrain_provider=DirectQuantTrainer())
    )
    policy_risk = PolicyRiskService(settings)
    trade_execution = ExecutionGatewayService(
        CoinbaseIntxBroker(),
        live_enabled=bool(settings.app.allow_live_orders and settings.execution.live_enabled),
    )
    agent_gateway = AgentGatewayService(
        pm_runner=_build_agent_runner(
            settings.agents.pm_agent,
            enabled=settings.agents.openclaw_enabled,
            timeout_seconds=_agent_timeout_seconds(settings=settings, agent_role="pm"),
        ),
        risk_runner=_build_agent_runner(
            settings.agents.risk_trader_agent,
            enabled=settings.agents.openclaw_enabled,
            timeout_seconds=_agent_timeout_seconds(settings=settings, agent_role="risk_trader"),
        ),
        macro_runner=_build_agent_runner(
            settings.agents.macro_event_analyst_agent,
            enabled=settings.agents.openclaw_enabled,
            timeout_seconds=_agent_timeout_seconds(settings=settings, agent_role="macro_event_analyst"),
        ),
        chief_runner=_build_agent_runner(
            settings.agents.crypto_chief_agent,
            enabled=settings.agents.openclaw_enabled,
            timeout_seconds=_agent_timeout_seconds(settings=settings, agent_role="crypto_chief"),
        ),
        session_controller=_build_session_controller(settings=settings, enabled=settings.agents.openclaw_enabled),
        agent_name_by_role={
            "pm": settings.agents.pm_agent,
            "risk_trader": settings.agents.risk_trader_agent,
            "macro_event_analyst": settings.agents.macro_event_analyst_agent,
            "crypto_chief": settings.agents.crypto_chief_agent,
        },
        memory_assets=memory_assets,
        market_data=market_data,
        news_events=news_events,
        quant_intelligence=quant_intelligence,
        policy_risk=policy_risk,
        trade_execution=trade_execution,
        notification_service=None,
        trigger_bridge=trigger_bridge,
        event_bus=event_bus,
    )
    notification_service = NotificationService(OpenClawNotificationProvider(), memory_assets)
    agent_gateway.notification_service = notification_service
    replay_frontend = ReplayFrontendService(memory_assets, settings)
    runtime_bridge_monitor = None
    if bool(settings.orchestrator.runtime_bridge_enabled):
        runtime_bridge_monitor = RuntimeBridgeMonitor(
            memory_assets=memory_assets,
            market_data=market_data,
            news_events=news_events,
            quant_intelligence=quant_intelligence,
            policy_risk=policy_risk,
            gateway=agent_gateway,
            config=RuntimeBridgeConfig(
                enabled=True,
                refresh_interval_seconds=int(settings.orchestrator.runtime_bridge_refresh_interval_seconds),
                max_age_seconds=int(settings.orchestrator.runtime_bridge_max_age_seconds),
            ),
        )
        agent_gateway.bind_runtime_bridge_monitor(
            runtime_bridge_monitor,
            max_age_seconds=int(settings.orchestrator.runtime_bridge_max_age_seconds),
        )
        try:
            runtime_bridge_monitor.refresh_once(reason="bootstrap")
        except Exception:
            pass
        runtime_bridge_monitor.start()
    executor = WorkflowCommandExecutor(
        memory_assets=memory_assets,
        event_bus=event_bus,
        market_data=market_data,
        news_events=news_events,
        quant_intelligence=quant_intelligence,
        policy_risk=policy_risk,
        trade_execution=trade_execution,
        agent_gateway=agent_gateway,
        notification_service=notification_service,
        replay_frontend=replay_frontend,
    )
    rt_trigger_monitor = None
    if bool(settings.orchestrator.rt_event_trigger_enabled):
        rt_trigger_monitor = RTTriggerMonitor(
            memory_assets=memory_assets,
            market_data=market_data,
            event_bus=event_bus,
            config=RTTriggerConfig(
                enabled=True,
                rt_job_id=str(settings.orchestrator.rt_event_trigger_job_id),
                scan_interval_seconds=int(settings.orchestrator.rt_event_trigger_scan_interval_seconds),
                global_cooldown_seconds=int(settings.orchestrator.rt_event_trigger_global_cooldown_seconds),
                key_cooldown_seconds=int(settings.orchestrator.rt_event_trigger_key_cooldown_seconds),
                max_runs_per_hour=int(settings.orchestrator.rt_event_trigger_max_runs_per_hour),
                position_heartbeat_minutes=int(settings.orchestrator.rt_event_trigger_position_heartbeat_minutes),
                flat_heartbeat_minutes=int(settings.orchestrator.rt_event_trigger_flat_heartbeat_minutes),
                exposure_drift_pct_of_exposure_budget=float(
                    settings.orchestrator.rt_event_trigger_exposure_drift_pct_of_exposure_budget
                ),
                execution_followup_delay_seconds=int(
                    settings.orchestrator.rt_event_trigger_execution_followup_delay_seconds
                ),
                cron_subprocess_timeout_seconds=int(
                    settings.orchestrator.rt_event_trigger_cron_subprocess_timeout_seconds
                ),
                max_leverage=float(settings.execution.max_leverage),
                openclaw_bin=str(settings.orchestrator.rt_event_trigger_openclaw_bin),
            ),
        )
    pm_recheck_monitor = None
    if bool(settings.orchestrator.pm_scheduled_recheck_enabled):
        pm_recheck_monitor = PMRecheckMonitor(
            memory_assets=memory_assets,
            event_bus=event_bus,
            config=PMRecheckConfig(
                enabled=True,
                pm_job_id=str(settings.orchestrator.pm_scheduled_recheck_job_id),
                scan_interval_seconds=int(settings.orchestrator.pm_scheduled_recheck_scan_interval_seconds),
                cron_subprocess_timeout_seconds=int(
                    settings.orchestrator.pm_scheduled_recheck_cron_subprocess_timeout_seconds
                ),
                openclaw_bin=str(settings.orchestrator.pm_scheduled_recheck_openclaw_bin),
            ),
        )
    risk_brake_monitor = None
    if bool(settings.orchestrator.risk_brake_enabled):
        risk_brake_monitor = RiskBrakeMonitor(
            memory_assets=memory_assets,
            market_data=market_data,
            policy_risk=policy_risk,
            trade_execution=trade_execution,
            event_bus=event_bus,
            config=RiskBrakeConfig(
                enabled=True,
                scan_interval_seconds=int(settings.orchestrator.risk_brake_scan_interval_seconds),
                rt_job_id=str(settings.orchestrator.risk_brake_rt_job_id),
                pm_job_id=str(settings.orchestrator.risk_brake_pm_job_id),
                cron_subprocess_timeout_seconds=int(
                    settings.orchestrator.risk_brake_cron_subprocess_timeout_seconds
                ),
                openclaw_bin=str(settings.orchestrator.risk_brake_openclaw_bin),
            ),
        )
    retro_prep_monitor = None
    if bool(settings.orchestrator.retro_prep_enabled):
        retro_prep_monitor = RetroPrepMonitor(
            memory_assets=memory_assets,
            agent_gateway=agent_gateway,
            event_bus=event_bus,
            config=RetroPrepConfig(
                enabled=True,
                scan_interval_seconds=int(settings.orchestrator.retro_prep_scan_interval_seconds),
                prep_hour_utc=int(settings.orchestrator.retro_prep_hour_utc),
                prep_minute_utc=int(settings.orchestrator.retro_prep_minute_utc),
                chief_job_id=str(settings.orchestrator.retro_prep_chief_job_id),
                cron_subprocess_timeout_seconds=int(
                    settings.orchestrator.retro_prep_cron_subprocess_timeout_seconds
                ),
                openclaw_bin=str(settings.orchestrator.retro_prep_openclaw_bin),
            ),
            cron_runner=OpenClawCronRunner(
                openclaw_bin=str(settings.orchestrator.retro_prep_openclaw_bin),
                timeout_seconds=int(settings.orchestrator.retro_prep_cron_subprocess_timeout_seconds),
            ),
        )
    workflow_orchestrator = WorkflowOrchestratorService(
        memory_assets=memory_assets,
        event_bus=event_bus,
        executor=executor,
        enable_daily_session_reset=True,
        rt_trigger_monitor=rt_trigger_monitor,
        pm_recheck_monitor=pm_recheck_monitor,
        risk_brake_monitor=risk_brake_monitor,
        retro_prep_monitor=retro_prep_monitor,
    )
    return ServiceContainer(
        settings=settings,
        event_bus=event_bus,
        memory_assets=memory_assets,
        market_data=market_data,
        news_events=news_events,
        quant_intelligence=quant_intelligence,
        policy_risk=policy_risk,
        trade_execution=trade_execution,
        agent_gateway=agent_gateway,
        notification_service=notification_service,
        replay_frontend=replay_frontend,
        workflow_orchestrator=workflow_orchestrator,
        runtime_bridge_monitor=runtime_bridge_monitor,
    )
