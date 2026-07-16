"""Service template: consistent startup/shutdown, DI, exception mapping, OpenAPI
customization at ``/swagger/v1/swagger.json``, health endpoints, and separate
HTTP (PORT=80) / gRPC (GRPC_PORT=81) listeners."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable

import grpc
import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from eshop_common.config import ServiceSettings
from eshop_common.health.core import (
    HealthCheckRegistry,
    write_health_check_ui_response,
    write_plain_response,
)
from eshop_common.observability import bind_request_context, configure_logging

logger = structlog.get_logger(__name__)

LifespanHook = Callable[[FastAPI], Awaitable[None]]


def create_service_app(
    service_name: str,
    settings: ServiceSettings | None = None,
    health: HealthCheckRegistry | None = None,
    on_startup: LifespanHook | None = None,
    on_shutdown: LifespanHook | None = None,
    version: str = "v1",
) -> FastAPI:
    settings = settings or ServiceSettings()
    health = health or HealthCheckRegistry()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(service_name)
        logger.info("service_starting", service=service_name)
        if on_startup is not None:
            await on_startup(app)
        yield
        logger.info("service_stopping", service=service_name)
        if on_shutdown is not None:
            await on_shutdown(app)

    root_path = settings.path_base or ""
    app = FastAPI(
        title=f"eShopOnContainers - {service_name}",
        version=version,
        lifespan=lifespan,
        root_path=root_path,
        docs_url="/swagger",
        openapi_url="/swagger/v1/swagger.json",
    )
    app.state.settings = settings
    app.state.health = health

    def custom_openapi() -> dict:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            routes=app.routes,
        )
        # Health endpoints are not part of the frozen .NET OpenAPI documents.
        for path in ("/hc", "/liveness"):
            schema.get("paths", {}).pop(path, None)
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]

    @app.middleware("http")
    async def request_context_middleware(request: Request, call_next):
        bind_request_context(request_id=request.headers.get("x-requestid"))
        return await call_next(request)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError):
        # ASP.NET Core model binding returns 400 Bad Request, not FastAPI's 422.
        return JSONResponse(
            status_code=400,
            content={"errors": jsonable_encoder(exc.errors()), "title": "Bad Request", "status": 400},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(_request: Request, exc: Exception):
        logger.error("unhandled_exception", exc_info=exc)
        return JSONResponse(status_code=500, content={"title": "An error occurred", "status": 500})

    @app.get("/hc", include_in_schema=False)
    async def hc():
        return write_health_check_ui_response(await health.run())

    @app.get("/liveness", include_in_schema=False)
    async def liveness():
        return write_plain_response(await health.run_liveness())

    return app


async def serve(
    app: FastAPI,
    grpc_server: grpc.aio.Server | None = None,
    settings: ServiceSettings | None = None,
    host: str = "0.0.0.0",
) -> None:
    """Run HTTP (PORT, default 80) and optional gRPC (GRPC_PORT, default 81) listeners
    with coordinated graceful shutdown."""
    settings = settings or ServiceSettings()
    config = uvicorn.Config(app, host=host, port=settings.http_port, log_config=None)
    server = uvicorn.Server(config)
    tasks = [asyncio.create_task(server.serve())]
    if grpc_server is not None:
        grpc_server.add_insecure_port(f"{host}:{settings.grpc_port}")
        await grpc_server.start()

        async def _grpc_wait() -> None:
            await grpc_server.wait_for_termination()

        tasks.append(asyncio.create_task(_grpc_wait()))
    try:
        await asyncio.gather(*tasks)
    finally:
        if grpc_server is not None:
            await grpc_server.stop(grace=5)
