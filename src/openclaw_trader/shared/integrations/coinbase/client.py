from __future__ import annotations

from ....config.models import CoinbaseCredentials
from .brokerage import CoinbaseBrokerageMixin
from .intx_api import CoinbaseIntxApiMixin
from .public import CoinbasePublicMarketMixin
from .transport import CoinbaseTransport


class CoinbaseAdvancedClient(
    CoinbaseIntxApiMixin,
    CoinbaseBrokerageMixin,
    CoinbasePublicMarketMixin,
    CoinbaseTransport,
):
    def __init__(
        self,
        credentials: CoinbaseCredentials,
        timeout: float = 20.0,
        *,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        super().__init__(
            credentials,
            timeout=timeout,
            max_retries=max_retries,
            retry_backoff_seconds=retry_backoff_seconds,
        )
