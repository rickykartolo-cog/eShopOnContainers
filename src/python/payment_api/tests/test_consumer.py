"""Simulated-payment decision behavior (ported from the observed .NET handler),
duplicate-delivery safety, and health-registry naming."""

import uuid
from datetime import UTC, datetime

from payment_test_helpers import make_settings

from payment_api.app import build_health_registry
from payment_api.consumers import PaymentEventConsumers
from payment_api.events import (
    OrderPaymentFailedIntegrationEvent,
    OrderPaymentSucceededIntegrationEvent,
    OrderStatusChangedToStockConfirmedIntegrationEvent,
)


def stock_confirmed(order_id: int = 42) -> OrderStatusChangedToStockConfirmedIntegrationEvent:
    return OrderStatusChangedToStockConfirmedIntegrationEvent(OrderId=order_id)


async def test_payment_succeeded_true_publishes_succeeded(event_bus):
    consumers = PaymentEventConsumers(make_settings(PaymentSucceeded="True"), event_bus)
    await consumers.subscribe_all()
    await event_bus.deliver(stock_confirmed())

    assert len(event_bus.published) == 1
    published = event_bus.published[0]
    assert isinstance(published, OrderPaymentSucceededIntegrationEvent)
    assert published.order_id == 42


async def test_payment_succeeded_false_publishes_failed(event_bus):
    consumers = PaymentEventConsumers(make_settings(PaymentSucceeded="False"), event_bus)
    await consumers.subscribe_all()
    await event_bus.deliver(stock_confirmed(order_id=7))

    assert len(event_bus.published) == 1
    published = event_bus.published[0]
    assert isinstance(published, OrderPaymentFailedIntegrationEvent)
    assert published.order_id == 7


async def test_payment_succeeded_defaults_to_true(event_bus):
    # appsettings.json default: "PaymentSucceeded": true
    consumers = PaymentEventConsumers(make_settings(), event_bus)
    await consumers.subscribe_all()
    await event_bus.deliver(stock_confirmed())

    assert isinstance(event_bus.published[0], OrderPaymentSucceededIntegrationEvent)


async def test_published_event_has_fresh_id_and_creation_date(event_bus):
    consumers = PaymentEventConsumers(make_settings(), event_bus)
    inbound = stock_confirmed()
    await consumers.subscribe_all()
    await event_bus.deliver(inbound)

    published = event_bus.published[0]
    assert published.id != inbound.id
    assert published.creation_date >= inbound.creation_date.replace(tzinfo=UTC)


async def test_duplicate_delivery_produces_no_additional_side_effects(event_bus):
    consumers = PaymentEventConsumers(make_settings(), event_bus)
    await consumers.subscribe_all()
    event = stock_confirmed()
    await event_bus.deliver(event)
    await event_bus.deliver(event)

    duplicate = OrderStatusChangedToStockConfirmedIntegrationEvent(
        OrderId=42, Id=event.id, CreationDate=datetime.now(UTC)
    )
    await event_bus.deliver(duplicate)

    assert len(event_bus.published) == 1


async def test_distinct_events_for_same_order_each_publish(event_bus):
    # Only the event Id deduplicates; the .NET handler publishes per event.
    consumers = PaymentEventConsumers(make_settings(), event_bus)
    await consumers.subscribe_all()
    await event_bus.deliver(stock_confirmed())
    await event_bus.deliver(
        OrderStatusChangedToStockConfirmedIntegrationEvent(OrderId=42, Id=uuid.uuid4())
    )

    assert len(event_bus.published) == 2


def test_health_registry_names_match_dotnet_registration():
    registry = build_health_registry(make_settings())
    names = [check.name for check in registry._checks]
    assert names == ["self", "payment-rabbitmqbus-check"]

    sb_registry = build_health_registry(
        make_settings(
            AzureServiceBusEnabled="True",
            EventBusConnection="Endpoint=sb://example.servicebus.windows.net/;SharedAccessKeyName=k;SharedAccessKey=v",
        )
    )
    assert [check.name for check in sb_registry._checks] == ["self", "payment-servicebus-check"]
