"""Full order state machine through the event consumers (oracle:
OrderingScenarios checkout -> order -> cancel), plus duplicate-delivery and
outbox atomicity/failure behavior."""

from __future__ import annotations

import uuid

import pytest
from eshop_common.outbox import EventState, IntegrationEventLogEntry
from sqlalchemy import select

from ordering_api.consumers import OrderingEventConsumers
from ordering_api.events import (
    GracePeriodConfirmedIntegrationEvent,
    OrderPaymentFailedIntegrationEvent,
    OrderPaymentSucceededIntegrationEvent,
    OrderStockConfirmedIntegrationEvent,
    UserCheckoutAcceptedIntegrationEvent,
)
from tests.test_http_contract import CHECKOUT_BODY, create_order


@pytest.fixture
def consumers(session_factory, event_bus, mediator) -> OrderingEventConsumers:
    return OrderingEventConsumers(session_factory, event_bus, mediator)


def published_names(event_bus) -> list[str]:
    return [type(e).__name__ for e in event_bus.published]


async def order_status(session_factory, order_id: int) -> str:
    from ordering_api import queries

    async with session_factory() as session:
        return (await queries.get_order(session, order_id))["status"]


async def test_checkout_publishes_started_and_submitted(session_factory, event_bus, mediator):
    await create_order(session_factory, event_bus, mediator)
    assert published_names(event_bus) == [
        "OrderStartedIntegrationEvent",
        "OrderStatusChangedToSubmittedIntegrationEvent",
    ]


async def test_full_happy_path_to_shipped(consumers, session_factory, event_bus, mediator):
    order_id = await create_order(session_factory, event_bus, mediator)

    await consumers.on_grace_period_confirmed(GracePeriodConfirmedIntegrationEvent(OrderId=order_id))
    assert await order_status(session_factory, order_id) == "awaitingvalidation"

    await consumers.on_order_stock_confirmed(OrderStockConfirmedIntegrationEvent(OrderId=order_id))
    assert await order_status(session_factory, order_id) == "stockconfirmed"

    await consumers.on_order_payment_succeeded(OrderPaymentSucceededIntegrationEvent(OrderId=order_id))
    assert await order_status(session_factory, order_id) == "paid"

    assert published_names(event_bus) == [
        "OrderStartedIntegrationEvent",
        "OrderStatusChangedToSubmittedIntegrationEvent",
        "OrderStatusChangedToAwaitingValidationIntegrationEvent",
        "OrderStatusChangedToStockConfirmedIntegrationEvent",
        "OrderStatusChangedToPaidIntegrationEvent",
    ]
    awaiting = event_bus.published[2]
    assert [(i.product_id, i.units) for i in awaiting.order_stock_items] == [(1, 2)]
    assert awaiting.buyer_name == CHECKOUT_BODY["UserName"]


async def test_payment_failed_cancels_order(consumers, session_factory, event_bus, mediator):
    order_id = await create_order(session_factory, event_bus, mediator)
    await consumers.on_grace_period_confirmed(GracePeriodConfirmedIntegrationEvent(OrderId=order_id))
    await consumers.on_order_stock_confirmed(OrderStockConfirmedIntegrationEvent(OrderId=order_id))
    await consumers.on_order_payment_failed(OrderPaymentFailedIntegrationEvent(OrderId=order_id))
    assert await order_status(session_factory, order_id) == "cancelled"
    assert published_names(event_bus)[-1] == "OrderStatusChangedToCancelledIntegrationEvent"


async def test_paid_order_cannot_be_cancelled(consumers, session_factory, event_bus, mediator):
    order_id = await create_order(session_factory, event_bus, mediator)
    await consumers.on_grace_period_confirmed(GracePeriodConfirmedIntegrationEvent(OrderId=order_id))
    await consumers.on_order_stock_confirmed(OrderStockConfirmedIntegrationEvent(OrderId=order_id))
    await consumers.on_order_payment_succeeded(OrderPaymentSucceededIntegrationEvent(OrderId=order_id))

    from ordering_api.models import OrderingDomainException

    with pytest.raises(OrderingDomainException):
        await consumers.on_order_payment_failed(OrderPaymentFailedIntegrationEvent(OrderId=order_id))
    assert await order_status(session_factory, order_id) == "paid"  # transition rejected


async def test_duplicate_checkout_delivery_creates_single_order(
    consumers, session_factory, event_bus, mediator
):
    request_id = uuid.uuid4()
    event = UserCheckoutAcceptedIntegrationEvent.model_validate(
        {**CHECKOUT_BODY, "RequestId": str(request_id)}
    )
    await consumers.on_user_checkout_accepted(event)
    await consumers.on_user_checkout_accepted(event)  # duplicate delivery
    started = [n for n in published_names(event_bus) if n == "OrderStartedIntegrationEvent"]
    assert len(started) == 1


async def test_duplicate_status_transition_is_noop(consumers, session_factory, event_bus, mediator):
    order_id = await create_order(session_factory, event_bus, mediator)
    await consumers.on_grace_period_confirmed(GracePeriodConfirmedIntegrationEvent(OrderId=order_id))
    before = len(event_bus.published)
    await consumers.on_grace_period_confirmed(GracePeriodConfirmedIntegrationEvent(OrderId=order_id))
    assert await order_status(session_factory, order_id) == "awaitingvalidation"
    assert len(event_bus.published) == before  # duplicate publishes nothing


async def test_checkout_without_request_id_is_rejected(consumers, session_factory, event_bus):
    event = UserCheckoutAcceptedIntegrationEvent.model_validate(
        {**CHECKOUT_BODY, "RequestId": str(uuid.UUID(int=0))}
    )
    await consumers.on_user_checkout_accepted(event)
    assert event_bus.published == []


async def test_outbox_rows_marked_published(consumers, session_factory, event_bus, mediator):
    await create_order(session_factory, event_bus, mediator)
    async with session_factory() as session:
        entries = (await session.execute(select(IntegrationEventLogEntry))).scalars().all()
    assert {e.State for e in entries} == {int(EventState.Published)}
    assert all(e.TimesSent == 1 for e in entries)
    assert all(
        e.EventTypeName.startswith("Ordering.API.Application.IntegrationEvents.Events.")
        for e in entries
    )


async def test_outbox_atomicity_when_broker_unavailable(consumers, session_factory, event_bus):
    """The aggregate + outbox rows commit atomically; a failed publish leaves the
    order persisted and the entries in PublishedFailed for retry."""
    event_bus.fail_publish = True
    event = UserCheckoutAcceptedIntegrationEvent.model_validate(
        {**CHECKOUT_BODY, "RequestId": str(uuid.uuid4())}
    )
    await consumers.on_user_checkout_accepted(event)

    async with session_factory() as session:
        entries = (await session.execute(select(IntegrationEventLogEntry))).scalars().all()
        assert entries and {e.State for e in entries} == {int(EventState.PublishedFailed)}

        from ordering_api.models import Order

        orders = (await session.execute(select(Order))).scalars().all()
        assert len(orders) == 1
        assert orders[0].OrderStatusId == 1  # submitted
