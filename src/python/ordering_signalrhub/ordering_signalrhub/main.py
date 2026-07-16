"""Application assembly: FastAPI (health endpoints) + Socket.IO hub + event bus.

Environment interface (unchanged from the .NET service / compose files):
``EventBusConnection``, ``EventBusUserName``, ``EventBusPassword``,
``EventBusRetryCount``, ``AzureServiceBusEnabled``, ``SubscriptionClientName``
(default ``Ordering.signalrhub`` as in appsettings.json), ``identityUrl``,
``IsClusterEnv`` + ``SignalrStoreConnectionString`` (Redis backplane),
``PATH_BASE``, ``PORT``.
"""

from __future__ import annotations

import socketio
import uvicorn
from eshop_common.auth import OidcJwtValidator
from eshop_common.config import ServiceSettings, Settings
from eshop_common.eventbus.base import EventBus
from eshop_common.eventbus.rabbitmq import RabbitMQEventBus
from eshop_common.eventbus.servicebus import AzureServiceBusEventBus
from eshop_common.health.checks import RabbitMQHealthCheck, ServiceBusHealthCheck
from eshop_common.health.core import HealthCheckRegistry
from eshop_common.template import create_service_app
from fastapi import FastAPI

from ordering_signalrhub.handlers import subscribe_all
from ordering_signalrhub.hub import NotificationHub

SERVICE_NAME = "Ordering.SignalrHub"
AUDIENCE = "orders.signalrhub"
DEFAULT_SUBSCRIPTION_CLIENT_NAME = "Ordering.signalrhub"


def _redis_url(connection_string: str) -> str:
    if connection_string.startswith(("redis://", "rediss://", "unix://")):
        return connection_string
    return f"redis://{connection_string}"


def build_event_bus(settings: Settings, service: ServiceSettings) -> EventBus:
    subscription = settings.get("SubscriptionClientName") or DEFAULT_SUBSCRIPTION_CLIENT_NAME
    if service.azure_service_bus_enabled:
        return AzureServiceBusEventBus(
            connection_string=service.event_bus_connection,
            subscription_name=subscription,
        )
    return RabbitMQEventBus(
        host=service.event_bus_connection,
        queue_name=subscription,
        username=service.event_bus_username,
        password=service.event_bus_password,
        retry_count=service.event_bus_retry_count,
    )


def build_health(settings: Settings, service: ServiceSettings) -> HealthCheckRegistry:
    health = HealthCheckRegistry()
    if service.azure_service_bus_enabled:
        health.add(
            ServiceBusHealthCheck(
                service.event_bus_connection,
                name="signalr-servicebus-check",
                tags=("servicebus",),
            )
        )
    else:
        health.add(
            RabbitMQHealthCheck(
                host=service.event_bus_connection,
                username=service.event_bus_username,
                password=service.event_bus_password,
                name="signalr-rabbitmqbus-check",
                tags=("rabbitmqbus",),
            )
        )
    return health


def build_app(
    settings: Settings | None = None,
    validator: OidcJwtValidator | None = None,
    event_bus: EventBus | None = None,
    client_manager: socketio.AsyncManager | None = None,
) -> socketio.ASGIApp:
    settings = settings or Settings()
    service = ServiceSettings(settings)

    validator = validator or OidcJwtValidator(authority=service.identity_url, audience=AUDIENCE)

    if client_manager is None and settings.get_bool("IsClusterEnv"):
        client_manager = socketio.AsyncRedisManager(
            _redis_url(settings.require("SignalrStoreConnectionString"))
        )

    hub = NotificationHub(validator, client_manager=client_manager)
    bus = event_bus or build_event_bus(settings, service)

    async def on_startup(_app: FastAPI) -> None:
        await subscribe_all(bus, hub)

    async def on_shutdown(_app: FastAPI) -> None:
        await bus.close()

    fastapi_app = create_service_app(
        SERVICE_NAME,
        settings=service,
        health=build_health(settings, service),
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )
    fastapi_app.state.hub = hub
    fastapi_app.state.event_bus = bus

    asgi = hub.asgi_app(other_asgi_app=fastapi_app)
    asgi.fastapi_app = fastapi_app  # type: ignore[attr-defined]
    return asgi


def main() -> None:
    settings = Settings()
    service = ServiceSettings(settings)
    uvicorn.run(build_app(settings), host="0.0.0.0", port=service.http_port)


if __name__ == "__main__":
    main()
