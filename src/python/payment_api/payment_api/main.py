"""Service entrypoint: HTTP health endpoints on PORT (80), matching the compose
interface of the .NET Payment.API container (no gRPC listener)."""

from __future__ import annotations

import asyncio

import structlog
from eshop_common.eventbus.base import EventBus
from eshop_common.eventbus.rabbitmq import RabbitMQEventBus
from eshop_common.template import serve
from tenacity import retry, stop_after_attempt, wait_exponential

from payment_api.app import build_health_registry, create_app
from payment_api.consumers import PaymentEventConsumers
from payment_api.settings import PaymentSettings

logger = structlog.get_logger(__name__)

# RabbitMQ may still be starting when the container comes up; retry like the
# .NET host's event-bus persistent-connection policy.
_startup_retry = retry(
    stop=stop_after_attempt(12),
    wait=wait_exponential(multiplier=1, min=1, max=15),
    reraise=True,
)


def create_event_bus(settings: PaymentSettings) -> EventBus:
    if settings.azure_service_bus_enabled:
        from eshop_common.eventbus.servicebus import AzureServiceBusEventBus

        return AzureServiceBusEventBus(
            connection_string=settings.event_bus_connection,
            subscription_name=settings.subscription_client_name,
        )
    return RabbitMQEventBus(
        host=settings.event_bus_connection,
        queue_name=settings.subscription_client_name,
        username=settings.event_bus_username,
        password=settings.event_bus_password,
        retry_count=settings.event_bus_retry_count,
    )


async def main() -> None:
    settings = PaymentSettings()
    event_bus = create_event_bus(settings)

    @_startup_retry
    async def connect_event_bus() -> None:
        consumers = PaymentEventConsumers(settings, event_bus)
        await consumers.subscribe_all()
        await event_bus.start_consuming()

    async def on_startup(app) -> None:
        await connect_event_bus()
        logger.info("payment_started")

    async def on_shutdown(app) -> None:
        await event_bus.close()

    health = build_health_registry(settings)
    app = create_app(
        settings,
        health,
        event_bus=event_bus,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )
    await serve(app, settings=settings)


if __name__ == "__main__":
    asyncio.run(main())
