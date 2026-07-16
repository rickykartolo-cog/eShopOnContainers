"""JWT bearer validation against an external OIDC IdP (discovery + rotating JWKS).

Validates issuer, signature, expiration, not-before, and the service's exact
audience. Known service audiences (must not change during migration):
``basket``, ``orders``, ``marketing``, ``locations``, ``orders.signalrhub``,
``webhooks``, ``mobileshoppingagg``, ``webshoppingagg``.
"""

from __future__ import annotations

import time

import httpx
import jwt
import structlog
from fastapi import HTTPException, Request

logger = structlog.get_logger(__name__)

KNOWN_AUDIENCES = frozenset(
    {
        "basket",
        "orders",
        "marketing",
        "locations",
        "orders.signalrhub",
        "webhooks",
        "mobileshoppingagg",
        "webshoppingagg",
    }
)


class OidcJwtValidator:
    def __init__(
        self,
        authority: str,
        audience: str,
        require_https: bool = False,
        jwks_cache_seconds: float = 300.0,
        leeway_seconds: float = 0.0,
    ) -> None:
        self._authority = authority.rstrip("/")
        self._audience = audience
        self._require_https = require_https
        self._jwks_cache_seconds = jwks_cache_seconds
        self._leeway = leeway_seconds
        self._issuer: str | None = None
        self._jwks_client: jwt.PyJWKClient | None = None
        self._discovered_at = 0.0

    @property
    def discovery_url(self) -> str:
        return f"{self._authority}/.well-known/openid-configuration"

    async def _ensure_discovered(self, force: bool = False) -> None:
        if (
            not force
            and self._jwks_client is not None
            and time.monotonic() - self._discovered_at < self._jwks_cache_seconds
        ):
            return
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(self.discovery_url)
            response.raise_for_status()
            document = response.json()
        self._issuer = document["issuer"]
        self._jwks_client = jwt.PyJWKClient(document["jwks_uri"], cache_keys=True)
        self._discovered_at = time.monotonic()

    async def validate(self, token: str) -> dict:
        await self._ensure_discovered()
        assert self._jwks_client is not None
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        except jwt.PyJWKClientError:
            # Key rotation: refresh discovery/JWKS once, then fail.
            await self._ensure_discovered(force=True)
            assert self._jwks_client is not None
            signing_key = self._jwks_client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256", "PS256"],
            audience=self._audience,
            issuer=self._issuer,
            leeway=self._leeway,
            options={
                "require": ["exp", "iss", "aud"],
                "verify_exp": True,
                "verify_nbf": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )


class JwtBearer:
    """FastAPI dependency enforcing bearer-token authentication."""

    def __init__(self, validator: OidcJwtValidator) -> None:
        self._validator = validator

    async def __call__(self, request: Request) -> dict:
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"})
        try:
            claims = await self._validator.validate(token)
        except jwt.PyJWTError as exc:
            logger.info("token_rejected", reason=type(exc).__name__)
            raise HTTPException(
                status_code=401, headers={"WWW-Authenticate": "Bearer"}
            ) from exc
        request.state.user = claims
        return claims
