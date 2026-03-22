from __future__ import annotations

from ...shared.protocols import EventFactory
from ..trade_gateway.market_data.models import DataIngestBundle
from .events import EVENT_FORECAST_GENERATED, EVENT_MODELS_RETRAINED, MODULE_NAME
from .models import CoinForecast
from .ports import QuantProvider


class QuantIntelligenceService:
    def __init__(self, provider: QuantProvider) -> None:
        self.provider = provider

    def get_latest_forecasts(self, market: DataIngestBundle) -> dict[str, CoinForecast]:
        return self.predict_market(market)

    def predict_market(self, market: DataIngestBundle) -> dict[str, CoinForecast]:
        return self.provider.predict_market(market)

    def build_forecast_events(self, *, trace_id: str, forecasts: dict[str, CoinForecast]):
        return [
            EventFactory.build(
                trace_id=trace_id,
                event_type=EVENT_FORECAST_GENERATED,
                source_module=MODULE_NAME,
                entity_type="coin_forecast",
                entity_id=coin,
                payload=forecast.model_dump(mode="json"),
            )
            for coin, forecast in forecasts.items()
        ]

    def retrain_models(self, coins: list[str] | None = None) -> dict[str, dict]:
        return self.provider.retrain(coins)

    def build_retrain_event(self, *, trace_id: str, payload: dict):
        return EventFactory.build(
            trace_id=trace_id,
            event_type=EVENT_MODELS_RETRAINED,
            source_module=MODULE_NAME,
            entity_type="model_retrain",
            payload=payload,
        )
