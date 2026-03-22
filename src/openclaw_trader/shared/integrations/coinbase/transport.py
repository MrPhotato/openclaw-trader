from __future__ import annotations

import ssl
import time
from typing import Any

import certifi
import httpx

from ....auth import CoinbaseJwtAuth
from ....config.models import CoinbaseCredentials


class CoinbaseTransport:
    RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
    PUBLIC_DATA_MIN_RETRIES = 4

    def __init__(
        self,
        credentials: CoinbaseCredentials,
        timeout: float = 20.0,
        *,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self.credentials = credentials
        self.auth = CoinbaseJwtAuth(credentials)
        self.base_url = credentials.api_base.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.retry_backoff_seconds = max(0.0, retry_backoff_seconds)
        self._client = self._build_client()

    def _build_client(self) -> httpx.Client:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            verify=ssl_context,
            trust_env=False,
        )

    def _reset_client(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass
        self._client = self._build_client()

    def close(self) -> None:
        self._client.close()

    def __del__(self) -> None:  # pragma: no cover
        try:
            self.close()
        except Exception:
            pass

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        max_retries: int | None = None,
    ) -> dict[str, Any]:
        retry_limit = self.max_retries if max_retries is None else max(0, max_retries)
        last_error: httpx.HTTPError | None = None
        for attempt in range(retry_limit + 1):
            token = self.auth.bearer_for_rest(method, path)
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            try:
                response = self._client.request(method, path, headers=headers, params=params, json=json)
                response.raise_for_status()
                if not response.content:
                    return {}
                return response.json()
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code not in self.RETRYABLE_STATUS_CODES or attempt >= retry_limit:
                    raise
            except httpx.RequestError as exc:
                last_error = exc
                self._reset_client()
                if attempt >= retry_limit:
                    raise
            time.sleep(self.retry_backoff_seconds * (2**attempt))
        if last_error is not None:  # pragma: no cover
            raise last_error
        raise RuntimeError(f"coinbase request exhausted retries: {method} {path}")
