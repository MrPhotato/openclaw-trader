from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ....shared.infra import EventBus
from ....shared.protocols import EventEnvelope
from ...agent_gateway.service import AgentGatewayService
from ...trade_gateway.market_data.service import DataIngestService
from ...trade_gateway.execution.service import ExecutionGatewayService
from ...news_events.service import NewsEventService
from ...notification_service.service import NotificationService
from ...policy_risk.service import PolicyRiskService
from ...quant_intelligence.service import QuantIntelligenceService
from ...replay_frontend.service import ReplayFrontendService
from ...state_memory.service import StateMemoryService


@dataclass
class WorkflowModuleServices:
    state_memory: StateMemoryService
    event_bus: EventBus
    market_data: DataIngestService
    news_events: NewsEventService
    quant_intelligence: QuantIntelligenceService
    policy_risk: PolicyRiskService
    trade_execution: ExecutionGatewayService
    agent_gateway: AgentGatewayService
    notification_service: NotificationService
    replay_frontend: ReplayFrontendService


class WorkflowEventRecorder:
    def __init__(self, services: WorkflowModuleServices) -> None:
        self.services = services

    def record_events(self, events: Iterable[EventEnvelope]) -> None:
        pending = list(events)
        while pending:
            event = pending.pop(0)
            self.services.state_memory.append_event(event)
            self._publish_best_effort(event)
            pending.extend(self.services.notification_service.handle_event(event))

    def _publish_best_effort(self, event: EventEnvelope) -> None:
        try:
            self.services.event_bus.publish(event)
        except Exception:
            return None
