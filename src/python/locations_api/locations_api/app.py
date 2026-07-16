"""FastAPI application factory for the Location service.

Uses the shared ``eshop_common`` template (swagger URLs, /hc, /liveness,
correlation, PATH_BASE) and overrides the OpenAPI document with the
golden-parity Swashbuckle-shaped document. Health-check names match the .NET
registration: ``self``, ``locations-mongodb-check``, ``locations-rabbitmqbus-check``.
"""

from __future__ import annotations

import re

from eshop_common.auth import JwtBearer, OidcJwtValidator
from eshop_common.config import ServiceSettings
from eshop_common.health.checks import MongoHealthCheck, RabbitMQHealthCheck
from eshop_common.health.core import HealthCheckRegistry
from eshop_common.template import create_service_app
from fastapi import FastAPI, HTTPException, Request
from motor.motor_asyncio import AsyncIOMotorClient

from locations_api.openapi_document import build_document
from locations_api.routes import router
from locations_api.service import LocationsService
from locations_api.settings import LocationSettings

_LOCATIONS_PREFIX = re.compile(r"^/api/v1/locations(/|$)", re.IGNORECASE)


def build_health_registry(settings: LocationSettings, mongo_client: AsyncIOMotorClient) -> HealthCheckRegistry:
    registry = HealthCheckRegistry()  # registers the "self" check
    registry.add(MongoHealthCheck(mongo_client, name="locations-mongodb-check"))
    if not settings.azure_service_bus_enabled:
        registry.add(
            RabbitMQHealthCheck(
                host=settings.event_bus_connection,
                username=settings.event_bus_username,
                password=settings.event_bus_password,
                name="locations-rabbitmqbus-check",
            )
        )
    return registry


def default_authenticator(settings: LocationSettings):
    """JWT bearer validation with the frozen audience ``locations``; resolves the
    ``sub`` claim exactly like the .NET IdentityService."""
    bearer = JwtBearer(OidcJwtValidator(settings.identity_url, audience="locations"))

    async def authenticate(request: Request) -> str:
        claims = await bearer(request)
        sub = claims.get("sub")
        if not sub:
            raise HTTPException(status_code=401, headers={"WWW-Authenticate": "Bearer"})
        return sub

    return authenticate


class ByPassAuthState:
    """Port of ByPassAuthMiddleware (enabled by ``UseLoadTest``): /noauth sets a
    fixed test user, /noauth/reset clears it, and an ``Email <user>`` Authorization
    header overrides it per request."""

    def __init__(self) -> None:
        self.current_user_id: str | None = None


def create_app(
    settings: LocationSettings,
    service: LocationsService,
    health: HealthCheckRegistry,
    authenticator=None,
    on_startup=None,
    on_shutdown=None,
) -> FastAPI:
    app = create_service_app(
        "Location HTTP API",
        settings=ServiceSettings(settings.settings),
        health=health,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )
    app.state.location_settings = settings
    app.state.locations_service = service
    app.state.authenticate = authenticator or default_authenticator(settings)

    document = build_document(settings.identity_url_external)

    def golden_openapi() -> dict:
        return document

    app.openapi = golden_openapi  # type: ignore[method-assign]

    # The golden document has no "servers" entry; keep FastAPI's openapi route
    # from injecting one derived from root_path. PATH_BASE is handled below.
    path_base = settings.path_base or ""
    app.root_path = ""

    bypass = ByPassAuthState()

    if settings.use_load_test:
        from fastapi.responses import PlainTextResponse

        real_authenticate = app.state.authenticate

        @app.get("/noauth", include_in_schema=False)
        async def noauth(request: Request):
            user_id = request.query_params.get("userid")
            if user_id:
                bypass.current_user_id = user_id
            return PlainTextResponse(f"User set to {bypass.current_user_id}")

        @app.get("/noauth/reset", include_in_schema=False)
        async def noauth_reset():
            bypass.current_user_id = None
            return PlainTextResponse("User set to none. Token required for protected endpoints.")

        async def bypass_authenticate(request: Request) -> str:
            current = bypass.current_user_id
            header = request.headers.get("Authorization", "")
            if header.startswith("Email ") and len(header) > len("Email "):
                current = header[len("Email "):]
            if current:
                return current
            return await real_authenticate(request)

        app.state.authenticate = bypass_authenticate

    @app.middleware("http")
    async def path_normalization_middleware(request: Request, call_next):
        # UsePathBase parity: requests may arrive with or without PATH_BASE.
        path = request.scope["path"]
        if path_base and path.startswith(path_base):
            request.scope["path"] = path = path[len(path_base):] or "/"
        # ASP.NET routing is case-insensitive and tolerates a trailing slash;
        # normalize the controller prefix.
        if _LOCATIONS_PREFIX.match(path):
            normalized = "/api/v1/locations" + path[len("/api/v1/locations"):]
            if len(normalized) > len("/api/v1/locations") and normalized.endswith("/"):
                normalized = normalized.rstrip("/")
            request.scope["path"] = normalized
        return await call_next(request)

    app.include_router(router)
    return app
