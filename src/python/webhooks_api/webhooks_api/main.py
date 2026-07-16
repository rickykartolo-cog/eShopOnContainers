"""Service entrypoint: HTTP on PORT (80), matching the compose interface of the
.NET Webhooks.API container (no gRPC listener)."""

from __future__ import annotations

import asyncio

import httpx
import structlog
from eshop_common.eventbus.rabbitmq import RabbitMQEventBus
from eshop_common.template import serve
from tenacity import retry, stop_after_attempt, wait_exponential

from webhooks_api.app import build_health_registry, create_app
from webhooks_api.consumers import WebhooksEventConsumers
from webhooks_api.db import (
    create_engine,
    create_session_factory,
    ensure_database,
    ensure_webhooks_database_exists,
)
from webhooks_api.sender import WebhooksSender
from webhooks_api.settings import WebhooksSettings

logger = structlog.get_logger(__name__)

# Dependencies (SQL Server, RabbitMQ) may still be starting when the container
# comes up; retry like the .NET host's MigrateDbContext / event-bus
# persistent-connection policy.
_startup_retry = retry(
    stop=stop_after_attempt(12),
    wait=wait_exponential(multiplier=1, min=1, max=15),
    reraise=True,
)


async def main() -> None:
    settings = WebhooksSettings()

    await _startup_retry(asyncio.to_thread)(ensure_webhooks_database_exists, settings.connection_string)
    engine = create_engine(settings.sqlalchemy_url())
    session_factory = create_session_factory(engine)

    event_bus = RabbitMQEventBus(
        host=settings.event_bus_connection,
        queue_name=settings.subscription_client_name,
        username=settings.event_bus_username,
        password=settings.event_bus_password,
        retry_count=settings.event_bus_retry_count,
    )

    hook_client = httpx.AsyncClient(timeout=100.0)
    sender = WebhooksSender(hook_client)
    grant_client = httpx.AsyncClient(timeout=100.0)

    @_startup_retry
    async def prepare_database() -> None:
        await ensure_database(engine)

    @_startup_retry
    async def connect_event_bus() -> None:
        consumers = WebhooksEventConsumers(session_factory, sender)
        await consumers.subscribe_all(event_bus)
        await event_bus.start_consuming()

    async def on_startup(app) -> None:
        await prepare_database()
        await connect_event_bus()
        logger.info("webhooks_started")

    async def on_shutdown(app) -> None:
        await event_bus.close()
        await hook_client.aclose()
        await grant_client.aclose()
        await engine.dispose()

    health = build_health_registry(settings, engine)
    app = create_app(
        settings,
        session_factory,
        health,
        grant_client=grant_client,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )
    await serve(app, settings=settings)


if __name__ == "__main__":
    asyncio.run(main())
