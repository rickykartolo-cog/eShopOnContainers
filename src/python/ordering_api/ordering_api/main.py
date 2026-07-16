"""Service entrypoint: HTTP on PORT (80) and gRPC on GRPC_PORT (81), matching
the compose interface of the .NET Ordering.API container."""

from __future__ import annotations

import asyncio

import structlog
from eshop_common.eventbus.rabbitmq import RabbitMQEventBus
from eshop_common.template import serve
from tenacity import retry, stop_after_attempt, wait_exponential

from ordering_api.app import DEFAULT_SWAGGER_PATH, build_health_registry, create_app
from ordering_api.consumers import OrderingEventConsumers
from ordering_api.db import (
    create_engine,
    create_session_factory,
    ensure_database,
    ensure_ordering_database_exists,
    seed,
)
from ordering_api.grpc_service import create_grpc_server
from ordering_api.handlers import build_mediator
from ordering_api.settings import OrderingSettings

logger = structlog.get_logger(__name__)

# Dependencies (SQL Server, RabbitMQ) may still be starting when the container
# comes up; retry like the .NET host's WaitForSqlAvailabilityAsync / event-bus
# persistent-connection policy.
_startup_retry = retry(
    stop=stop_after_attempt(12),
    wait=wait_exponential(multiplier=1, min=1, max=15),
    reraise=True,
)


async def main() -> None:
    settings = OrderingSettings()

    await _startup_retry(asyncio.to_thread)(ensure_ordering_database_exists, settings.connection_string)
    engine = create_engine(settings.sqlalchemy_url())
    session_factory = create_session_factory(engine)
    mediator = build_mediator()

    event_bus = RabbitMQEventBus(
        host=settings.event_bus_connection,
        queue_name=settings.subscription_client_name,
        username=settings.event_bus_username,
        password=settings.event_bus_password,
        retry_count=settings.event_bus_retry_count,
    )

    @_startup_retry
    async def prepare_database() -> None:
        await ensure_database(engine)
        async with session_factory() as session:
            await seed(session)

    @_startup_retry
    async def connect_event_bus() -> None:
        consumers = OrderingEventConsumers(session_factory, event_bus, mediator)
        await consumers.subscribe_all()
        await event_bus.start_consuming()

    async def on_startup(app) -> None:
        await prepare_database()
        await connect_event_bus()
        logger.info("ordering_started")

    async def on_shutdown(app) -> None:
        await event_bus.close()
        await engine.dispose()

    health = build_health_registry(settings, engine)
    app = create_app(
        settings,
        session_factory,
        health,
        mediator,
        event_bus=event_bus,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        swagger_path=settings.swagger_path or DEFAULT_SWAGGER_PATH,
    )
    grpc_server = create_grpc_server(session_factory, mediator, event_bus)
    await serve(app, grpc_server=grpc_server, settings=settings)


if __name__ == "__main__":
    asyncio.run(main())
