from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from openclaw_trader.app.dependencies import ServiceContainer
from openclaw_trader.config.models import AgentSettings, BusSettings, ExecutionSettings, NotificationSettings, QuantSettings, StorageSettings, SystemSettings, WorkflowSettings
from openclaw_trader.modules.agent_gateway import AgentGatewayService
from openclaw_trader.modules.agent_gateway.adapters import DeterministicAgentRunner
from openclaw_trader.modules.trade_gateway.market_data import (
    AccountSnapshot,
    CompressedPriceSeries,
    DataIngestService,
    ExecutionHistorySnapshot,
    MarketContextNormalized,
    MarketSnapshotNormalized,
    OpenOrderSnapshot,
    PriceSeriesPoint,
    ProductMetadataSnapshot,
    PortfolioPositionSnapshot,
    PortfolioSnapshot,
)
from openclaw_trader.modules.trade_gateway.execution import ExecutionDecision, ExecutionGatewayService, ExecutionResult, PortfolioView
from openclaw_trader.modules.news_events import NewsDigestEvent, NewsEventService
from openclaw_trader.modules.notification_service import NotificationResult, NotificationService
from openclaw_trader.modules.policy_risk import PolicyRiskService
from openclaw_trader.modules.quant_intelligence import CoinForecast, HorizonSignal, QuantIntelligenceService
from openclaw_trader.modules.replay_frontend import ReplayFrontendService
from openclaw_trader.modules.state_memory import StateMemoryRepository, StateMemoryService
from openclaw_trader.modules.workflow_orchestrator import WorkflowOrchestratorService
from openclaw_trader.modules.workflow_orchestrator.trigger_bridge import WorkflowTriggerBridge
from openclaw_trader.modules.workflow_orchestrator.handlers import WorkflowCommandExecutor
from openclaw_trader.shared.infra import InMemoryEventBus, SqliteDatabase


class FakeMarketDataProvider:
    def collect_market(self, coins: list[str]) -> dict[str, MarketSnapshotNormalized]:
        return {
            coin: MarketSnapshotNormalized(
                snapshot_id=f"{coin.lower()}-1",
                coin=coin,
                product_id=f"{coin}-PERP-INTX",
                mark_price="100",
                index_price="99.8",
                funding_rate="0.0001",
                premium="0.002",
                open_interest="1000",
                day_notional_volume="1000000",
                spread_bps=5.0,
                trading_status="online",
            )
            for coin in coins
        }

    def collect_accounts(self, coins: list[str]) -> dict[str, AccountSnapshot]:
        return {
            coin: AccountSnapshot(
                coin=coin,
                total_equity_usd="1000",
                available_equity_usd="800",
                current_side="long",
                current_notional_usd="200",
                current_leverage="2",
                current_quantity="2",
                entry_price="95",
                unrealized_pnl_usd="10",
                liquidation_price="70",
            )
            for coin in coins
        }

    def collect_portfolio(self) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            starting_equity_usd="990",
            unrealized_pnl_usd="10",
            total_equity_usd="1000",
            available_equity_usd="800",
            total_exposure_usd="200",
            open_order_hold_usd="25",
            positions=[
                PortfolioPositionSnapshot(
                    coin="BTC",
                    side="long",
                    quantity="2",
                    notional_usd="200",
                    leverage="2",
                    entry_price="95",
                    unrealized_pnl_usd="10",
                    position_share_pct_of_exposure_budget=4.0,
                )
            ],
        )

    def collect_product_metadata(self, coins: list[str]) -> dict[str, ProductMetadataSnapshot]:
        return {
            coin: ProductMetadataSnapshot(
                coin=coin,
                product_id=f"{coin}-PERP-INTX",
                tick_size="0.1",
                size_increment="0.001",
                min_size="0.001",
                min_notional="10",
                max_leverage="5",
                trading_status="online",
            )
            for coin in coins
        }

    def collect_market_context(self, coins: list[str]) -> dict[str, MarketContextNormalized]:
        payload: dict[str, MarketContextNormalized] = {}
        for coin in coins:
            payload[coin] = MarketContextNormalized(
                coin=coin,
                product_id=f"{coin}-PERP-INTX",
                compressed_price_series={
                    "15m": CompressedPriceSeries(
                        window="15m",
                        granularity="FIFTEEN_MINUTE",
                        points=[
                            PriceSeriesPoint(timestamp=1, close="100"),
                            PriceSeriesPoint(timestamp=2, close="101"),
                        ],
                        change_pct=1.0,
                    ),
                    "1h": CompressedPriceSeries(window="1h", granularity="ONE_HOUR", points=[], change_pct=1.2),
                    "4h": CompressedPriceSeries(window="4h", granularity="FOUR_HOUR", points=[], change_pct=2.2),
                    "24h": CompressedPriceSeries(window="24h", granularity="ONE_DAY", points=[], change_pct=4.2),
                },
                shape_summary="uptrend|range|normal|above_mean",
            )
        return payload

    def collect_execution_history(self, coins: list[str]) -> dict[str, ExecutionHistorySnapshot]:
        return {
            coin: ExecutionHistorySnapshot(
                coin=coin,
                product_id=f"{coin}-PERP-INTX",
                recent_orders=[{"order_id": f"ord-{coin.lower()}"}],
                recent_fills=[{"fill_id": f"fill-{coin.lower()}"}],
                failure_sources=[],
                open_orders=[
                    OpenOrderSnapshot(
                        order_id=f"open-{coin.lower()}",
                        status="OPEN",
                        side="BUY",
                        notional_usd="25",
                    )
                ],
            )
            for coin in coins
        }


class FakeNewsProvider:
    def __init__(self, severity: str = "low") -> None:
        self.severity = severity

    def sync(self) -> list[NewsDigestEvent]:
        return self.latest()

    def latest(self) -> list[NewsDigestEvent]:
        return [
            NewsDigestEvent(
                news_id="news-1",
                source="test",
                title="Macro headline",
                url="https://example.com",
                severity=self.severity,
                published_at=datetime.now(UTC),
            )
        ]


class FakeQuantProvider:
    def __init__(self, side_12h: str = "long", side_4h: str = "long", side_1h: str = "flat") -> None:
        self.side_12h = side_12h
        self.side_4h = side_4h
        self.side_1h = side_1h

    def predict_market(self, market) -> dict[str, CoinForecast]:
        return {
            coin: CoinForecast(
                coin=coin,
                horizons={
                    "12h": HorizonSignal(horizon="12h", side=self.side_12h, confidence=0.72),
                    "4h": HorizonSignal(horizon="4h", side=self.side_4h, confidence=0.68),
                    "1h": HorizonSignal(horizon="1h", side=self.side_1h, confidence=0.51),
                },
            )
            for coin in market.market
        }

    def retrain(self, coins: list[str] | None = None) -> dict[str, dict]:
        target = coins or ["BTC", "ETH", "SOL"]
        return {coin: {"status": "ok"} for coin in target}


class FakeBroker:
    def __init__(self) -> None:
        self.executed = []

    def execute_plan(self, plan) -> ExecutionResult:
        self.executed.append(plan)
        return ExecutionResult(plan_id=plan.plan_id, success=True, exchange_order_id=f"ord-{plan.plan_id}", fills=[plan.model_dump(mode="json")])

    def portfolio(self) -> PortfolioView:
        return PortfolioView(total_equity_usd="1000", available_equity_usd="750", positions=[])


class FakeNotificationProvider:
    def __init__(self) -> None:
        self.commands = []

    def send(self, command) -> NotificationResult:
        self.commands.append(command)
        return NotificationResult(notification_id=command.notification_id, delivered=True, provider_message_id=command.notification_id)


class FakeSessionController:
    def __init__(self) -> None:
        self.resets: list[dict[str, object]] = []

    def reset(self, *, agent_role: str, session_id: str, reset_command: str = "/new") -> dict[str, object]:
        payload = {
            "agent_role": agent_role,
            "session_id": session_id,
            "effective_session_id": session_id,
            "reset_command": reset_command,
            "success": True,
            "mode": "fake",
        }
        self.resets.append(payload)
        return payload


@dataclass
class TestHarness:
    tempdir: TemporaryDirectory
    container: ServiceContainer
    event_bus: InMemoryEventBus
    fake_broker: FakeBroker
    fake_notifier: FakeNotificationProvider
    fake_session_controller: FakeSessionController

    def wait_for_workflow(self, trace_id: str, *, timeout_seconds: float = 5.0):
        return self.container.workflow_orchestrator.wait_for_workflow(trace_id, timeout_seconds=timeout_seconds)

    def cleanup(self) -> None:
        self.container.close()
        self.tempdir.cleanup()


def build_test_settings(sqlite_path: Path) -> SystemSettings:
    return SystemSettings(
        runtime_root=sqlite_path.parent.parent,
        bus=BusSettings(rabbitmq_url="amqp://guest:guest@127.0.0.1:5672/%2F", exchange_name="test.topic"),
        storage=StorageSettings(sqlite_path=sqlite_path),
        quant=QuantSettings(
            interval="15m",
            history_bars=1500,
            forecast_horizons={"1h": 4, "4h": 16, "12h": 48},
            target_move_threshold_pct=0.0025,
            round_trip_cost_pct=0.0012,
            retrain_after_minutes=360,
            min_confidence=0.43,
            min_long_short_probability=0.39,
            meta_min_confidence=0.48,
            uncertainty_disagreement_caution=0.32,
            uncertainty_disagreement_freeze=0.45,
            uncertainty_regime_fit_caution=0.30,
            uncertainty_regime_fit_freeze=0.24,
        ),
        execution=ExecutionSettings(
            exchange="coinbase_intx",
            supported_coins=["BTC", "ETH", "SOL"],
            live_enabled=True,
            max_leverage=5.0,
            max_total_exposure_pct_of_exposure_budget=100.0,
            max_order_pct_of_exposure_budget=33.0,
            max_position_pct_of_exposure_budget=66.0,
        ),
        workflow=WorkflowSettings(
            owner_channel="owner-channel",
            owner_to="user:owner",
            owner_account_id="default",
            fresh_news_minutes=15,
        ),
        agents=AgentSettings(),
        notification=NotificationSettings(
            default_channel="owner-channel",
            default_recipient="user:owner",
            chief_recipient="agent:crypto-chief",
        ),
    )


def build_test_harness(*, news_severity: str = "low", side_12h: str = "long", side_4h: str = "long", side_1h: str = "flat") -> TestHarness:
    tempdir = TemporaryDirectory()
    sqlite_path = Path(tempdir.name) / "state" / "test.db"
    settings = build_test_settings(sqlite_path)
    event_bus = InMemoryEventBus()
    state_memory = StateMemoryService(StateMemoryRepository(SqliteDatabase(sqlite_path)))
    trigger_bridge = WorkflowTriggerBridge(state_memory)
    state_memory.ensure_bootstrap_parameter(
        "quant_defaults",
        "global",
        {
            "min_confidence": settings.quant.min_confidence,
            "horizon_roles": {"12h": "market_direction_context", "4h": "market_structure_context", "1h": "short_horizon_context"},
        },
        operator="test",
        reason="bootstrap",
    )
    market_data = DataIngestService(FakeMarketDataProvider())
    news_events = NewsEventService(FakeNewsProvider(severity=news_severity))
    quant_intelligence = QuantIntelligenceService(FakeQuantProvider(side_12h=side_12h, side_4h=side_4h, side_1h=side_1h))
    policy_risk = PolicyRiskService(settings)
    fake_broker = FakeBroker()
    trade_execution = ExecutionGatewayService(fake_broker, live_enabled=settings.execution.live_enabled)
    fake_session_controller = FakeSessionController()
    learning_root = Path(tempdir.name) / "workspaces"
    learning_paths = {
        "pm": str(learning_root / "pm" / ".learnings" / "pm.md"),
        "risk_trader": str(learning_root / "risk_trader" / ".learnings" / "risk_trader.md"),
        "macro_event_analyst": str(learning_root / "macro_event_analyst" / ".learnings" / "macro_event_analyst.md"),
        "crypto_chief": str(learning_root / "crypto_chief" / ".learnings" / "crypto_chief.md"),
    }
    agent_gateway = AgentGatewayService(
        pm_runner=DeterministicAgentRunner(),
        risk_runner=DeterministicAgentRunner(),
        macro_runner=DeterministicAgentRunner(),
        chief_runner=DeterministicAgentRunner(),
        session_controller=fake_session_controller,
        learning_path_by_role=learning_paths,
        state_memory=state_memory,
        market_data=market_data,
        news_events=news_events,
        quant_intelligence=quant_intelligence,
        policy_risk=policy_risk,
        trade_execution=trade_execution,
        trigger_bridge=trigger_bridge,
        event_bus=event_bus,
    )
    fake_notifier = FakeNotificationProvider()
    notification_service = NotificationService(fake_notifier, state_memory)
    agent_gateway.notification_service = notification_service
    replay_frontend = ReplayFrontendService(state_memory, settings)
    executor = WorkflowCommandExecutor(
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
    orchestrator = WorkflowOrchestratorService(
        state_memory=state_memory,
        event_bus=event_bus,
        executor=executor,
    )
    container = ServiceContainer(
        settings=settings,
        event_bus=event_bus,  # type: ignore[arg-type]
        state_memory=state_memory,
        market_data=market_data,
        news_events=news_events,
        quant_intelligence=quant_intelligence,
        policy_risk=policy_risk,
        trade_execution=trade_execution,
        agent_gateway=agent_gateway,
        notification_service=notification_service,
        replay_frontend=replay_frontend,
        workflow_orchestrator=orchestrator,
    )
    return TestHarness(
        tempdir=tempdir,
        container=container,
        event_bus=event_bus,
        fake_broker=fake_broker,
        fake_notifier=fake_notifier,
        fake_session_controller=fake_session_controller,
    )
