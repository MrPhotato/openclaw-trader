from __future__ import annotations

from urllib.parse import urlparse

from cdp.auth.utils.jwt import JwtOptions, generate_jwt

from .config import CoinbaseCredentials


class CoinbaseJwtAuth:
    def __init__(self, credentials: CoinbaseCredentials):
        self.credentials = credentials
        self._host = urlparse(credentials.api_base).netloc

    def bearer_for_rest(self, method: str, path: str) -> str:
        return generate_jwt(
            JwtOptions(
                api_key_id=self.credentials.api_key_id,
                api_key_secret=self.credentials.api_key_secret,
                request_method=method.upper(),
                request_host=self._host,
                request_path=path,
            )
        )
