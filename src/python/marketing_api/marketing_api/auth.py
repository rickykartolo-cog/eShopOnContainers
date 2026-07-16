"""Authentication ports: JWT bearer validation (audience ``marketing``) via the
shared OIDC validator, plus the ``UseLoadTest`` ``ByPassAuthMiddleware`` behavior
(``/noauth`` + ``Email`` scheme) preserved from the .NET service."""

from __future__ import annotations

import jwt
import structlog
from eshop_common.auth import OidcJwtValidator
from fastapi import Request

logger = structlog.get_logger(__name__)

AUDIENCE = "marketing"


class JwtUserResolver:
    """Resolves the authenticated user's ``sub`` claim from a bearer token,
    matching ``IdentityService.GetUserIdentity``."""

    def __init__(self, authority: str) -> None:
        self._validator = OidcJwtValidator(authority=authority, audience=AUDIENCE)

    async def __call__(self, request: Request) -> str | None:
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        try:
            claims = await self._validator.validate(token)
        except jwt.PyJWTError as exc:
            logger.info("token_rejected", reason=type(exc).__name__)
            return None
        return claims.get("sub")


class BypassAuthState:
    """State backing the ``ByPassAuthMiddleware`` port (``UseLoadTest`` only)."""

    def __init__(self) -> None:
        self.current_user_id: str | None = None

    def resolve(self, request: Request) -> str | None:
        current = self.current_user_id
        header = request.headers.get("Authorization", "")
        if header.startswith("Email ") and len(header) > len("Email "):
            current = header[len("Email "):]
        return current
