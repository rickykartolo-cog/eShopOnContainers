"""FastAPI application factory for the Payment service.

Payment exposes no HTTP API (no swagger golden); only the health endpoints from
the shared ``eshop_common`` template. Health-check names match the .NET
registration: ``self`` plus ``payment-rabbitmqbus-check`` (RabbitMQ) or
``payment-servicebus-check`` (Azure Service Bus).
"""

from __future__ import annotations

from eshop_common.config import ServiceSettings
from eshop_common.health.checks import RabbitMQHealthCheck, ServiceBusHealthCheck
from eshop_common.health.core import HealthCheckRegistry
from eshop_common.template import create_service_app
from fastapi import FastAPI

from payment_api.settings import PaymentSettings


def build_health_registry(settings: PaymentSettings) -> HealthCheckRegistry:
    registry = HealthCheckRegistry()  # registers the "self" check
    if settings.azure_service_bus_enabled:
        registry.add(
            ServiceBusHealthCheck(
                connection_string=settings.event_bus_connection,
                topic_name="eshop_event_bus",
                name="payment-servicebus-check",
                tags=("servicebus",),
            )
        )
    else:
        registry.add(
            RabbitMQHealthCheck(
                host=settings.event_bus_connection,
                username=settings.event_bus_username,
                password=settings.event_bus_password,
                name="payment-rabbitmqbus-check",
                tags=("rabbitmqbus",),
            )
        )
    return registry


def create_app(
    settings: PaymentSettings,
    health: HealthCheckRegistry,
    event_bus=None,
    on_startup=None,
    on_shutdown=None,
) -> FastAPI:
    app = create_service_app(
        "Payment HTTP API",
        settings=ServiceSettings(settings.settings),
        health=health,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )
    app.state.payment_settings = settings
    app.state.event_bus = event_bus
    return app
