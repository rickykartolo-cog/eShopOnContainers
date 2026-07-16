"""Port of ``GrantUrlTesterService``: OPTIONS the grant URL with the
``X-eshop-whtoken`` header and require a success status plus the same token
echoed back. The .NET same-origin check compares scheme and port only (its
host comparison is `firstUrl.Host == firstUrl.Host`, always true); that
observed behavior is preserved."""

from __future__ import annotations

from urllib.parse import urlsplit

import httpx
import structlog

from webhooks_api.sender import TOKEN_HEADER

logger = structlog.get_logger(__name__)

_DEFAULT_PORTS = {"http": 80, "https": 443}


class GrantUrlTesterService:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def test_grant_url(self, url_hook: str, url: str, token: str) -> bool:
        if not self._check_same_origin(url_hook, url):
            logger.warning("grant_url_origin_mismatch", url_hook=url_hook, url=url)
            return False

        logger.info("sending_grant_options", url=url)
        try:
            response = await self._client.request("OPTIONS", url, headers={TOKEN_HEADER: token})
        except httpx.HTTPError as exc:
            logger.warning("grant_url_options_failed", error=type(exc).__name__)
            return False
        token_received = response.headers.get(TOKEN_HEADER)
        token_expected = token if token and token.strip() else None
        logger.info(
            "grant_url_response",
            status_code=response.status_code,
            url=url,
            token_received=token_received,
            token_expected=token_expected,
        )
        return response.is_success and token_received == token_expected

    @staticmethod
    def _check_same_origin(url_hook: str, url: str) -> bool:
        first = urlsplit(url_hook)
        second = urlsplit(url)
        first_port = first.port or _DEFAULT_PORTS.get(first.scheme, None)
        second_port = second.port or _DEFAULT_PORTS.get(second.scheme, None)
        # Scheme + port only — the .NET host comparison is a no-op (see docstring).
        return first.scheme == second.scheme and first_port == second_port
