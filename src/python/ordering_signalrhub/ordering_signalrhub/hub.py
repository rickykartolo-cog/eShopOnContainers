"""Socket.IO notification hub preserving the SignalR hub's user-visible semantics.

- served at ``/hub/notificationhub`` (Socket.IO engine path, same URL prefix the
  Envoy gateways already route with websocket upgrade)
- browser authentication via ``access_token`` in the connection query string
  (or the Socket.IO ``auth`` payload), validated against the OIDC IdP with
  audience ``orders.signalrhub``
- each connection joins a room keyed by the authenticated user's name, matching
  the .NET group key ``Context.User.Identity.Name`` (the ``unique_name`` claim)
- messages: ``UpdatedOrderState`` with ``{ orderId, status }`` — the same
  camelCase payload the SignalR JSON protocol delivered to the browser
- Redis backplane (``AsyncRedisManager``) in clustered environments
"""

from __future__ import annotations

import urllib.parse
from typing import Any

import jwt
import socketio
import structlog
from eshop_common.auth import OidcJwtValidator

logger = structlog.get_logger(__name__)

HUB_PATH = "/hub/notificationhub"
UPDATED_ORDER_STATE = "UpdatedOrderState"


def extract_access_token(environ: dict, auth: Any) -> str | None:
    """Token from the Socket.IO ``auth`` payload or the ``access_token`` query
    string (the browser mechanism the frozen contract requires)."""
    if isinstance(auth, dict):
        token = auth.get("access_token") or auth.get("token")
        if token:
            return str(token)
    query = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
    values = query.get("access_token")
    return values[0] if values else None


def resolve_user_name(claims: dict) -> str | None:
    """Group key parity with .NET ``Context.User.Identity.Name``: the JWT handler
    maps ``unique_name`` to the identity name (``sub`` mapping removed)."""
    return claims.get("unique_name") or claims.get("name") or claims.get("preferred_username")


class NotificationHub:
    def __init__(
        self,
        validator: OidcJwtValidator,
        client_manager: socketio.AsyncManager | None = None,
    ) -> None:
        self._validator = validator
        self.sio = socketio.AsyncServer(
            async_mode="asgi",
            client_manager=client_manager,
            cors_allowed_origins="*",
        )
        self.sio.on("connect", self._on_connect)
        self.sio.on("disconnect", self._on_disconnect)

    async def _on_connect(self, sid: str, environ: dict, auth: Any = None) -> None:
        token = extract_access_token(environ, auth)
        if not token:
            raise socketio.exceptions.ConnectionRefusedError("authentication required")
        try:
            claims = await self._validator.validate(token)
        except jwt.PyJWTError as exc:
            logger.info("hub_token_rejected", reason=type(exc).__name__)
            raise socketio.exceptions.ConnectionRefusedError("unauthorized") from exc
        user_name = resolve_user_name(claims)
        if not user_name:
            raise socketio.exceptions.ConnectionRefusedError("unauthorized")
        await self.sio.enter_room(sid, user_name)
        await self.sio.save_session(sid, {"user_name": user_name})
        logger.info("hub_client_connected", user=user_name)

    async def _on_disconnect(self, sid: str) -> None:
        session = await self.sio.get_session(sid)
        user_name = session.get("user_name") if session else None
        if user_name:
            await self.sio.leave_room(sid, user_name)
            logger.info("hub_client_disconnected", user=user_name)

    async def send_order_status(self, buyer_name: str, order_id: int, status: str) -> None:
        await self.sio.emit(
            UPDATED_ORDER_STATE,
            {"orderId": order_id, "status": status},
            room=buyer_name,
        )

    def asgi_app(self, other_asgi_app: Any = None) -> socketio.ASGIApp:
        return socketio.ASGIApp(self.sio, other_asgi_app=other_asgi_app, socketio_path=HUB_PATH)
