"""Service entrypoint: HTTP on PORT (80), matching the compose interface of the
.NET Marketing.API container."""

from __future__ import annotations

import asyncio

import structlog
from eshop_common.eventbus.rabbitmq import RabbitMQEventBus
from eshop_common.template import serve
from motor.motor_asyncio import AsyncIOMotorClient
from tenacity import retry, stop_after_attempt, wait_exponential

from marketing_api.app import build_health_registry, create_app
from marketing_api.consumers import MarketingEventConsumers
from marketing_api.db import (
    create_engine,
    create_session_factory,
    ensure_database,
    ensure_marketing_database_exists,
)
from marketing_api.read_model import MarketingDataRepository
from marketing_api.seed import seed
from marketing_api.settings import MarketingSettings

logger = structlog.get_logger(__name__)

# Dependencies (SQL Server, MongoDB, RabbitMQ) may still be starting when the
# container comes up; retry like the .NET host's startup policies.
_startup_retry = retry(
    stop=stop_after_attempt(12),
    wait=wait_exponential(multiplier=1, min=1, max=15),
    reraise=True,
)


async def main() -> None:
    settings = MarketingSettings()

    await _startup_retry(asyncio.to_thread)(ensure_marketing_database_exists, settings.connection_string)
    engine = create_engine(settings.sqlalchemy_url())
    session_factory = create_session_factory(engine)

    mongo_client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongo_connection_string)
    repository = MarketingDataRepository(mongo_client[settings.mongo_database])

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
        consumers = MarketingEventConsumers(repository, event_bus)
        await consumers.subscribe_all()
        await event_bus.start_consuming()

    async def on_startup(app) -> None:
        await prepare_database()
        await connect_event_bus()
        logger.info("marketing_started")

    async def on_shutdown(app) -> None:
        await event_bus.close()
        await engine.dispose()
        mongo_client.close()

    health = build_health_registry(settings, engine, mongo_client)
    app = create_app(
        settings,
        session_factory,
        health,
        repository,
        event_bus=event_bus,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )
    await serve(app, settings=settings)


if __name__ == "__main__":
    asyncio.run(main())
