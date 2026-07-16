"""Bearer authentication for the Basket routes (audience ``basket``).

Uses the shared ``eshop_common.auth.OidcJwtValidator`` (OIDC discovery +
rotating JWKS against ``identityUrl``). Failures produce the same observable
behavior as ASP.NET Core's JwtBearer middleware: ``401`` with an empty body and
a ``WWW-Authenticate: Bearer`` challenge header.
"""

from __future__ import annotations

from typing import Protocol

import jwt
import structlog
from eshop_common.auth import OidcJwtValidator
from fastapi import Request, Response

logger = structlog.get_logger(__name__)

AUDIENCE = "basket"


class Authenticator(Protocol):
    async def authenticate(self, request: Request) -> dict | Response: ...


def challenge(error: str | None = None) -> Response:
    header = "Bearer" if error is None else f'Bearer error="{error}"'
    return Response(status_code=401, headers={"WWW-Authenticate": header})


class OidcAuthenticator:
    def __init__(self, identity_url: str) -> None:
        self._validator = OidcJwtValidator(authority=identity_url, audience=AUDIENCE, require_https=False)

    async def authenticate(self, request: Request) -> dict | Response:
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return challenge()
        try:
            return await self._validator.validate(token)
        except jwt.PyJWTError as exc:
            logger.info("token_rejected", reason=type(exc).__name__)
            return challenge("invalid_token")


def user_identity(claims: dict) -> str:
    """Port of ``IdentityService.GetUserIdentity`` (the ``sub`` claim)."""
    return claims["sub"]


def user_name(claims: dict) -> str:
    """Port of ``User.FindFirst(ClaimTypes.Name)``: with the default inbound
    claim-type map the JWT ``unique_name`` claim maps to ``ClaimTypes.Name``;
    IdentityServer4 access tokens for this app carry ``unique_name``/``name``."""
    return claims.get("unique_name") or claims.get("name") or claims.get("preferred_username") or ""
