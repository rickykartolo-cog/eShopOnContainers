"""Service entrypoint: HTTP on PORT (80) and gRPC on GRPC_PORT (81), matching
the compose interface of the .NET Basket.API container."""

from __future__ import annotations

import asyncio

import redis.asyncio as aioredis
import structlog
from eshop_common.eventbus.rabbitmq import RabbitMQEventBus
from eshop_common.template import serve
from tenacity import retry, stop_after_attempt, wait_exponential

from basket_api.app import build_health_registry, create_app
from basket_api.auth import OidcAuthenticator
from basket_api.consumers import BasketEventConsumers
from basket_api.grpc_service import create_grpc_server
from basket_api.repository import RedisBasketRepository
from basket_api.settings import BasketSettings

logger = structlog.get_logger(__name__)

# Dependencies (Redis, RabbitMQ, identity) may still be starting when the
# container comes up; retry like the .NET host's startup connection policy.
_startup_retry = retry(
    stop=stop_after_attempt(12),
    wait=wait_exponential(multiplier=1, min=1, max=15),
    reraise=True,
)


async def main() -> None:
    settings = BasketSettings()

    redis_client = aioredis.from_url(settings.redis_url())
    repository = RedisBasketRepository(redis_client)

    event_bus = RabbitMQEventBus(
        host=settings.event_bus_connection,
        queue_name=settings.subscription_client_name,
        username=settings.event_bus_username,
        password=settings.event_bus_password,
        retry_count=settings.event_bus_retry_count,
    )

    @_startup_retry
    async def connect_redis() -> None:
        # Like the .NET host, verify Redis availability during startup instead
        # of making the first request pay the connection cost.
        await redis_client.ping()

    @_startup_retry
    async def connect_event_bus() -> None:
        consumers = BasketEventConsumers(repository, event_bus)
        await consumers.subscribe_all()
        await event_bus.start_consuming()

    async def on_startup(app) -> None:
        await connect_redis()
        await connect_event_bus()
        logger.info("basket_started")

    async def on_shutdown(app) -> None:
        await event_bus.close()
        await redis_client.aclose()

    health = build_health_registry(settings, redis_client)
    authenticator = OidcAuthenticator(settings.identity_url)
    app_kwargs = {}
    if settings.proto_path is not None:
        app_kwargs["proto_path"] = settings.proto_path
    app = create_app(
        settings,
        repository,
        health,
        authenticator,
        event_bus=event_bus,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        **app_kwargs,
    )
    grpc_server = create_grpc_server(repository)
    await serve(app, grpc_server=grpc_server, settings=settings)


if __name__ == "__main__":
    asyncio.run(main())
