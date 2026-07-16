"""FastAPI application factory for the Basket service.

Uses the shared ``eshop_common`` template (swagger URLs, /hc, /liveness,
correlation, PATH_BASE) and overrides the OpenAPI document with the
golden-parity Swashbuckle-shaped document. Health-check names match the .NET
registration: ``self``, ``redis-check``, ``basket-rabbitmqbus-check``.
"""

from __future__ import annotations

import re
from pathlib import Path

from eshop_common.config import ServiceSettings
from eshop_common.health.checks import RabbitMQHealthCheck, RedisHealthCheck
from eshop_common.health.core import HealthCheckRegistry
from eshop_common.template import create_service_app
from fastapi import FastAPI, Request

from basket_api.auth import Authenticator
from basket_api.openapi_document import build_document
from basket_api.repository import RedisBasketRepository
from basket_api.routes import router
from basket_api.settings import BasketSettings

_BASKET_PREFIX = re.compile(r"^/api/v1/basket(/|$)", re.IGNORECASE)

DEFAULT_PROTO_PATH = Path(__file__).resolve().parents[3] / "Services/Basket/Basket.API/Proto/basket.proto"


def build_health_registry(settings: BasketSettings, redis_client) -> HealthCheckRegistry:
    registry = HealthCheckRegistry()  # registers the "self" check
    registry.add(RedisHealthCheck(redis_client, name="redis-check"))
    if not settings.azure_service_bus_enabled:
        registry.add(
            RabbitMQHealthCheck(
                host=settings.event_bus_connection,
                username=settings.event_bus_username,
                password=settings.event_bus_password,
                name="basket-rabbitmqbus-check",
            )
        )
    return registry


def create_app(
    settings: BasketSettings,
    repository: RedisBasketRepository,
    health: HealthCheckRegistry,
    authenticator: Authenticator,
    event_bus=None,
    on_startup=None,
    on_shutdown=None,
    proto_path: Path = DEFAULT_PROTO_PATH,
) -> FastAPI:
    app = create_service_app(
        "Basket HTTP API",
        settings=ServiceSettings(settings.settings),
        health=health,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )
    app.state.basket_settings = settings
    app.state.repository = repository
    app.state.authenticator = authenticator
    app.state.event_bus = event_bus
    app.state.proto_path = proto_path

    document = build_document(settings.identity_url_external or "http://localhost:5105")

    def golden_openapi() -> dict:
        return document

    app.openapi = golden_openapi  # type: ignore[method-assign]

    # The golden document has no "servers" entry; keep FastAPI's openapi route
    # from injecting one derived from root_path. PATH_BASE is handled below.
    path_base = settings.path_base or ""
    app.root_path = ""

    @app.middleware("http")
    async def path_normalization_middleware(request: Request, call_next):
        # UsePathBase parity: requests may arrive with or without PATH_BASE.
        path = request.scope["path"]
        if path_base and path.startswith(path_base):
            request.scope["path"] = path = path[len(path_base):] or "/"
        # ASP.NET routing is case-insensitive; normalize the controller prefix.
        if _BASKET_PREFIX.match(path):
            request.scope["path"] = "/api/v1/basket" + path[len("/api/v1/basket"):]
        return await call_next(request)

    app.include_router(router)
    return app
