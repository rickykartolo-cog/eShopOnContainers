"""FastAPI application factory for the Marketing service.

Uses the shared ``eshop_common`` template (swagger URLs, /hc, /liveness,
correlation, PATH_BASE) and overrides the OpenAPI document with the
golden-parity Swashbuckle-shaped document. Health-check names match the .NET
registration: ``self``, ``MarketingDB-check``, ``MarketingDB-mongodb-check``,
``marketing-rabbitmqbus-check``.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from eshop_common.config import ServiceSettings
from eshop_common.health.checks import MongoHealthCheck, RabbitMQHealthCheck, SqlServerHealthCheck
from eshop_common.health.core import HealthCheckRegistry
from eshop_common.template import create_service_app
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from marketing_api.auth import BypassAuthState, JwtUserResolver
from marketing_api.openapi_document import build_document
from marketing_api.routes import router
from marketing_api.settings import MarketingSettings

_CAMPAIGNS_PREFIX = re.compile(r"^/api/v1/campaigns(/|$)", re.IGNORECASE)

UserResolver = Callable[[Request], Awaitable[str | None]]


def build_health_registry(settings: MarketingSettings, engine, mongo_client) -> HealthCheckRegistry:
    registry = HealthCheckRegistry()  # registers the "self" check
    registry.add(SqlServerHealthCheck(engine, name="MarketingDB-check"))
    registry.add(MongoHealthCheck(mongo_client, name="MarketingDB-mongodb-check"))
    if not settings.azure_service_bus_enabled:
        registry.add(
            RabbitMQHealthCheck(
                host=settings.event_bus_connection,
                username=settings.event_bus_username,
                password=settings.event_bus_password,
                name="marketing-rabbitmqbus-check",
            )
        )
    return registry


def create_app(
    settings: MarketingSettings,
    session_factory,
    health: HealthCheckRegistry,
    repository,
    event_bus=None,
    user_resolver: UserResolver | None = None,
    on_startup=None,
    on_shutdown=None,
) -> FastAPI:
    app = create_service_app(
        "Marketing HTTP API",
        settings=ServiceSettings(settings.settings),
        health=health,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )
    app.state.marketing_settings = settings
    app.state.session_factory = session_factory
    app.state.marketing_data_repository = repository
    app.state.event_bus = event_bus

    if user_resolver is None:
        user_resolver = JwtUserResolver(settings.identity_url)
    bypass = BypassAuthState() if settings.use_load_test else None

    document = build_document(settings.identity_url_external or "http://localhost:5105")

    def golden_openapi() -> dict:
        return document

    app.openapi = golden_openapi  # type: ignore[method-assign]

    # The golden document has no "servers" entry; keep FastAPI's openapi route
    # from injecting one derived from root_path. PATH_BASE is handled below.
    path_base = settings.path_base or ""
    app.root_path = ""

    @app.middleware("http")
    async def session_middleware(request: Request, call_next):
        # UsePathBase parity: requests may arrive with or without PATH_BASE.
        path = request.scope["path"]
        if path_base and path.startswith(path_base):
            request.scope["path"] = path = path[len(path_base):] or "/"
            request.scope["root_path"] = path_base  # Location headers include PathBase
        # ByPassAuthMiddleware parity (UseLoadTest only).
        if bypass is not None:
            if path == "/noauth":
                user_id = request.query_params.get("userid")
                if user_id:
                    bypass.current_user_id = user_id
                return PlainTextResponse(f"User set to {bypass.current_user_id}", media_type="text/string")
            if path == "/noauth/reset":
                bypass.current_user_id = None
                return PlainTextResponse(
                    "User set to none. Token required for protected endpoints.", media_type="text/string"
                )
        # ASP.NET routing is case-insensitive; normalize the controller prefix.
        if _CAMPAIGNS_PREFIX.match(path):
            request.scope["path"] = "/api/v1/campaigns" + path[len("/api/v1/campaigns"):]
        request.state.user_sub = None
        if bypass is not None:
            request.state.user_sub = bypass.resolve(request)
        if request.state.user_sub is None:
            request.state.user_sub = await user_resolver(request)
        async with request.app.state.session_factory() as session:
            request.state.session = session
            return await call_next(request)

    app.include_router(router)
    return app
