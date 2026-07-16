"""FastAPI application factory for the Catalog service.

Uses the shared ``eshop_common`` template (swagger URLs, /hc, /liveness,
correlation, PATH_BASE) and overrides the OpenAPI document with the
golden-parity Swashbuckle-shaped document. Health-check names match the .NET
registration: ``self``, ``CatalogDB-check``, ``catalog-rabbitmqbus-check``.
"""

from __future__ import annotations

import re
from pathlib import Path

from eshop_common.config import ServiceSettings
from eshop_common.health.checks import RabbitMQHealthCheck, SqlServerHealthCheck
from eshop_common.health.core import HealthCheckRegistry
from eshop_common.template import create_service_app
from fastapi import FastAPI, Request

from catalog_api.openapi_document import build_document
from catalog_api.routes import router
from catalog_api.settings import CatalogSettings

_CATALOG_PREFIX = re.compile(r"^/api/v1/catalog(/|$)", re.IGNORECASE)

DEFAULT_PROTO_PATH = Path(__file__).resolve().parents[3] / "Services/Catalog/Catalog.API/Proto/catalog.proto"


def build_health_registry(settings: CatalogSettings, engine) -> HealthCheckRegistry:
    registry = HealthCheckRegistry()  # registers the "self" check
    registry.add(SqlServerHealthCheck(engine, name="CatalogDB-check"))
    if not settings.azure_service_bus_enabled:
        registry.add(
            RabbitMQHealthCheck(
                host=settings.event_bus_connection,
                username=settings.event_bus_username,
                password=settings.event_bus_password,
                name="catalog-rabbitmqbus-check",
            )
        )
    return registry


def create_app(
    settings: CatalogSettings,
    session_factory,
    health: HealthCheckRegistry,
    event_bus=None,
    on_startup=None,
    on_shutdown=None,
    proto_path: Path = DEFAULT_PROTO_PATH,
) -> FastAPI:
    app = create_service_app(
        "Catalog HTTP API",
        settings=ServiceSettings(settings.settings),
        health=health,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )
    app.state.catalog_settings = settings
    app.state.session_factory = session_factory
    app.state.event_bus = event_bus
    app.state.proto_path = proto_path

    document = build_document()

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
        # ASP.NET routing is case-insensitive; normalize the controller prefix.
        if _CATALOG_PREFIX.match(path):
            request.scope["path"] = "/api/v1/catalog" + path[len("/api/v1/catalog"):]
        async with request.app.state.session_factory() as session:
            request.state.session = session
            if request.app.state.event_bus is not None:
                from catalog_api.integration import CatalogIntegrationEventService

                request.state.integration_service = CatalogIntegrationEventService(
                    session, request.app.state.event_bus
                )
            return await call_next(request)

    app.include_router(router)
    return app
