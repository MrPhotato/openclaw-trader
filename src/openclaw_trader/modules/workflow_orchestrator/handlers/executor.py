from __future__ import annotations

from ....shared.infra import EventBus
from ...agent_gateway.service import AgentGatewayService
from ...trade_gateway.market_data.service import DataIngestService
from ...trade_gateway.execution.service import ExecutionGatewayService
from ...news_events.service import NewsEventService
from ...notification_service.service import NotificationService
from ...policy_risk.service import PolicyRiskService
from ...quant_intelligence.service import QuantIntelligenceService
from ...replay_frontend.service import ReplayFrontendService
from ...state_memory.service import StateMemoryService
from ..models import ManualTriggerCommand
from .base import WorkflowModuleServices
from .control import ControlWorkflowHandler
from .market import MarketWorkflowHandler


class WorkflowCommandExecutor:
    def __init__(
        self,
        *,
        state_memory: StateMemoryService,
        event_bus: EventBus,
        market_data: DataIngestService,
        news_events: NewsEventService,
        quant_intelligence: QuantIntelligenceService,
        policy_risk: PolicyRiskService,
        trade_execution: ExecutionGatewayService,
        agent_gateway: AgentGatewayService,
        notification_service: NotificationService,
        replay_frontend: ReplayFrontendService,
    ) -> None:
        services = WorkflowModuleServices(
            state_memory=state_memory,
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
        self.control_handler = ControlWorkflowHandler(services)
        self.market_handler = MarketWorkflowHandler(services)

    def handle(self, command: ManualTriggerCommand, *, workflow_id: str, trace_id: str) -> dict:
        if self.control_handler.can_handle(command):
            return self.control_handler.handle(command, workflow_id=workflow_id, trace_id=trace_id)
        return self.market_handler.handle(command, workflow_id=workflow_id, trace_id=trace_id)
