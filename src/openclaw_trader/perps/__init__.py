from __future__ import annotations

from typing import cast

from ..coinbase import CoinbaseAdvancedClient
from ..config import RuntimeConfig, load_coinbase_credentials
from ..state import StateStore
from .base import PerpEngine
from .coinbase_intx import CoinbaseIntxContext, CoinbaseIntxEngine
from .hyperliquid import HyperliquidPaperContext, HyperliquidPaperEngine, HyperliquidPublicClient


def build_perp_engine(runtime: RuntimeConfig, state: StateStore) -> PerpEngine:
    exchange = str(runtime.perps.exchange).strip().lower()
    if exchange in {"coinbase", "coinbase-intx", "coinbase_intx"}:
        portfolio_key = f"perp:{exchange}:portfolio_uuid"
        credentials = load_coinbase_credentials()
        client = CoinbaseAdvancedClient(credentials)
        portfolio_uuid = str(state.get_value(portfolio_key) or "").strip()
        if not portfolio_uuid:
            permissions = client.get_key_permissions()
            portfolio_uuid = str(permissions.get("portfolio_uuid") or "").strip()
            if portfolio_uuid:
                state.set_value(portfolio_key, portfolio_uuid)
        if not portfolio_uuid:
            raise ValueError("coinbase intx portfolio_uuid missing from key permissions")
        return cast(
            PerpEngine,
            CoinbaseIntxEngine(
                CoinbaseIntxContext(
                    config=runtime.perps,
                    client=client,
                    state=state,
                    portfolio_uuid=portfolio_uuid,
                )
            ),
        )
    return cast(
        PerpEngine,
        HyperliquidPaperEngine(
            HyperliquidPaperContext(
                config=runtime.perps,
                client=HyperliquidPublicClient(runtime.perps.api_base),
                state=state,
            )
        ),
    )


__all__ = [
    "PerpEngine",
    "build_perp_engine",
    "CoinbaseIntxEngine",
    "CoinbaseIntxContext",
    "HyperliquidPaperEngine",
    "HyperliquidPublicClient",
]
