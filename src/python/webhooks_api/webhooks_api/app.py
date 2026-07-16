"""FastAPI application factory for the Webhooks service.

Uses the shared ``eshop_common`` template (swagger URLs, /hc, /liveness,
correlation, PATH_BASE) and overrides the OpenAPI document with the
golden-parity Swashbuckle-shaped document. Health-check names match the .NET
registration: ``self``, ``WebhooksApiDb-check`` (the .NET service registers no
event-bus check).
"""

from __future__ import annotations

import re

import httpx
from eshop_common.auth import OidcJwtValidator
from eshop_common.config import ServiceSettings
from eshop_common.health.checks import SqlServerHealthCheck
from eshop_common.health.core import HealthCheckRegistry
from eshop_common.template import create_service_app
from fastapi import FastAPI, Request

from webhooks_api.grant_tester import GrantUrlTesterService
from webhooks_api.openapi_document import build_document
from webhooks_api.routes import router
from webhooks_api.settings import WebhooksSettings

_WEBHOOKS_PREFIX = re.compile(r"^/api/v1/webhooks(/|$)", re.IGNORECASE)


def build_health_registry(settings: WebhooksSettings, engine) -> HealthCheckRegistry:
    registry = HealthCheckRegistry()  # registers the "self" check
    registry.add(SqlServerHealthCheck(engine, name="WebhooksApiDb-check"))
    return registry


def create_app(
    settings: WebhooksSettings,
    session_factory,
    health: HealthCheckRegistry,
    jwt_validator: OidcJwtValidator | None = None,
    grant_client: httpx.AsyncClient | None = None,
    on_startup=None,
    on_shutdown=None,
) -> FastAPI:
    app = create_service_app(
        "Webhooks HTTP API",
        settings=ServiceSettings(settings.settings),
        health=health,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )
    app.state.webhooks_settings = settings
    app.state.session_factory = session_factory
    app.state.jwt_validator = jwt_validator or OidcJwtValidator(
        authority=settings.identity_url, audience="webhooks", require_https=False
    )
    app.state.grant_url_tester = GrantUrlTesterService(
        grant_client if grant_client is not None else httpx.AsyncClient(timeout=100.0)
    )

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
        # ASP.NET routing is case-insensitive; normalize the controller prefix.
        if _WEBHOOKS_PREFIX.match(path):
            request.scope["path"] = "/api/v1/webhooks" + path[len("/api/v1/webhooks"):]
        async with request.app.state.session_factory() as session:
            request.state.session = session
            return await call_next(request)

    app.include_router(router)
    return app
