"""Service entrypoint: HTTP on PORT (80), matching the compose interface of the
.NET Locations.API container."""

from __future__ import annotations

import asyncio

import structlog
from eshop_common.eventbus.rabbitmq import RabbitMQEventBus
from eshop_common.template import serve
from motor.motor_asyncio import AsyncIOMotorClient
from tenacity import retry, stop_after_attempt, wait_exponential

from locations_api.app import build_health_registry, create_app
from locations_api.repository import LocationsRepository
from locations_api.seed import seed
from locations_api.service import LocationsService
from locations_api.settings import LocationSettings

logger = structlog.get_logger(__name__)

# Dependencies (MongoDB, RabbitMQ) may still be starting when the container
# comes up; retry like the .NET host's startup/seed behavior.
_startup_retry = retry(
    stop=stop_after_attempt(12),
    wait=wait_exponential(multiplier=1, min=1, max=15),
    reraise=True,
)


async def main() -> None:
    settings = LocationSettings()

    mongo_client: AsyncIOMotorClient = AsyncIOMotorClient(settings.connection_string, tz_aware=True)
    repository = LocationsRepository(mongo_client[settings.database])

    event_bus = RabbitMQEventBus(
        host=settings.event_bus_connection,
        queue_name=settings.subscription_client_name,
        username=settings.event_bus_username,
        password=settings.event_bus_password,
        retry_count=settings.event_bus_retry_count,
    )
    service = LocationsService(repository, event_bus)

    @_startup_retry
    async def prepare_database() -> None:
        await seed(repository)

    async def on_startup(app) -> None:
        await prepare_database()
        logger.info("locations_started")

    async def on_shutdown(app) -> None:
        await event_bus.close()
        mongo_client.close()

    health = build_health_registry(settings, mongo_client)
    app = create_app(
        settings,
        service,
        health,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )
    await serve(app, settings=settings)


if __name__ == "__main__":
    asyncio.run(main())
