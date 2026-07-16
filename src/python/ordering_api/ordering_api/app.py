"""FastAPI application factory for the Ordering service.

Uses the shared ``eshop_common`` template (swagger URLs, /hc, /liveness,
correlation, PATH_BASE) and serves the frozen Swashbuckle OpenAPI document
byte-for-byte. Health-check names match the .NET registration: ``self``,
``OrderingDB-check``, ``ordering-rabbitmqbus-check``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from eshop_common.auth import JwtBearer, OidcJwtValidator
from eshop_common.config import ServiceSettings
from eshop_common.health.checks import RabbitMQHealthCheck, SqlServerHealthCheck
from eshop_common.health.core import HealthCheckRegistry
from eshop_common.template import create_service_app
from fastapi import FastAPI, Request

from ordering_api.routes import router
from ordering_api.settings import OrderingSettings

_ORDERS_PREFIX = re.compile(r"^/api/v1/orders(/|$)", re.IGNORECASE)

DEFAULT_SWAGGER_PATH = Path(__file__).resolve().parent / "contracts" / "ordering.swagger.json"


def build_health_registry(settings: OrderingSettings, engine) -> HealthCheckRegistry:
    registry = HealthCheckRegistry()  # registers the "self" check
    registry.add(SqlServerHealthCheck(engine, name="OrderingDB-check"))
    if not settings.azure_service_bus_enabled:
        registry.add(
            RabbitMQHealthCheck(
                host=settings.event_bus_connection,
                username=settings.event_bus_username,
                password=settings.event_bus_password,
                name="ordering-rabbitmqbus-check",
            )
        )
    return registry


def create_app(
    settings: OrderingSettings,
    session_factory,
    health: HealthCheckRegistry,
    mediator,
    event_bus=None,
    jwt_bearer: JwtBearer | None = None,
    on_startup=None,
    on_shutdown=None,
    swagger_path: Path = DEFAULT_SWAGGER_PATH,
) -> FastAPI:
    app = create_service_app(
        "Ordering HTTP API",
        settings=ServiceSettings(settings.settings),
        health=health,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )
    app.state.ordering_settings = settings
    app.state.session_factory = session_factory
    app.state.event_bus = event_bus
    app.state.mediator = mediator
    app.state.jwt_bearer = jwt_bearer or JwtBearer(
        OidcJwtValidator(authority=settings.identity_url, audience="orders")
    )

    document = json.loads(swagger_path.read_text(encoding="utf-8"))

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
        # ASP.NET routing is case-insensitive; every orders segment is either a
        # lowercase literal or the numeric {orderId}, so lowercasing is safe.
        if _ORDERS_PREFIX.match(path):
            request.scope["path"] = path.lower()
        async with request.app.state.session_factory() as session:
            request.state.session = session
            return await call_next(request)

    app.include_router(router)
    return app
