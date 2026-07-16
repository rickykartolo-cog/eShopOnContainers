"""Outbox atomicity, publish state tracking, consumer semantics, and
duplicate-delivery idempotency (§6.3)."""

import json
import uuid

from eshop_common.outbox import EventState, IntegrationEventLogEntry
from sqlalchemy import select

from catalog_api.consumers import CatalogEventConsumers
from catalog_api.events import (
    OrderStockConfirmedIntegrationEvent,
    ProductPriceChangedIntegrationEvent,
)
from catalog_api.integration import CatalogIntegrationEventService
from catalog_api.models import CatalogItem

PRICE_EVENT = dict(ProductId=1, NewPrice="21.50", OldPrice="19.50")


async def first_item_id(session_factory) -> int:
    async with session_factory() as session:
        return (await session.execute(select(CatalogItem.Id).order_by(CatalogItem.Id))).scalars().first()


async def test_save_event_and_changes_is_atomic(seeded_session_factory, event_bus):
    item_id = await first_item_id(seeded_session_factory)
    async with seeded_session_factory() as session:
        item = (await session.execute(select(CatalogItem).where(CatalogItem.Id == item_id))).scalar_one()
        item.Price = 555
        event = ProductPriceChangedIntegrationEvent(**PRICE_EVENT)
        service = CatalogIntegrationEventService(session, event_bus)
        await service.save_event_and_catalog_context_changes(event)

    async with seeded_session_factory() as session:
        stored = (await session.execute(select(CatalogItem).where(CatalogItem.Id == item_id))).scalar_one()
        assert int(stored.Price) == 555
        entry = (
            await session.execute(
                select(IntegrationEventLogEntry).where(IntegrationEventLogEntry.EventId == event.id)
            )
        ).scalar_one()
        assert entry.State == int(EventState.NotPublished)
        assert entry.TransactionId is not None


async def test_rollback_leaves_no_partial_state(seeded_session_factory, event_bus):
    item_id = await first_item_id(seeded_session_factory)
    event = ProductPriceChangedIntegrationEvent(**PRICE_EVENT)
    async with seeded_session_factory() as session:
        item = (await session.execute(select(CatalogItem).where(CatalogItem.Id == item_id))).scalar_one()
        original_price = item.Price
        item.Price = 777
        service = CatalogIntegrationEventService(session, event_bus)
        await service._log_service.save_event(event, uuid.uuid4())
        await session.rollback()

    async with seeded_session_factory() as session:
        stored = (await session.execute(select(CatalogItem).where(CatalogItem.Id == item_id))).scalar_one()
        assert stored.Price == original_price
        entries = (
            await session.execute(
                select(IntegrationEventLogEntry).where(IntegrationEventLogEntry.EventId == event.id)
            )
        ).scalars().all()
        assert entries == []


async def test_publish_failure_marks_published_failed(seeded_session_factory, event_bus):
    event = ProductPriceChangedIntegrationEvent(**PRICE_EVENT)
    event_bus.fail_publish = True
    async with seeded_session_factory() as session:
        service = CatalogIntegrationEventService(session, event_bus)
        await service.save_event_and_catalog_context_changes(event)
        # Publish failures are recorded, not raised (matching the .NET service).
        await service.publish_through_event_bus(event)

    async with seeded_session_factory() as session:
        entry = (
            await session.execute(
                select(IntegrationEventLogEntry).where(IntegrationEventLogEntry.EventId == event.id)
            )
        ).scalar_one()
        assert entry.State == int(EventState.PublishedFailed)


def awaiting_validation_payload(items, event_id=None):
    return json.dumps(
        {
            "OrderId": 42,
            "OrderStatus": "awaitingvalidation",
            "BuyerName": "alice@eshop",
            "OrderStockItems": [{"ProductId": pid, "Units": units} for pid, units in items],
            "Id": str(event_id or uuid.uuid4()),
            "CreationDate": "2020-01-02T03:04:05.678Z",
        }
    )


async def test_awaiting_validation_confirms_stock(seeded_session_factory, event_bus):
    item_id = await first_item_id(seeded_session_factory)
    consumers = CatalogEventConsumers(seeded_session_factory, event_bus)
    await consumers.subscribe_all()
    await event_bus.deliver(
        "OrderStatusChangedToAwaitingValidationIntegrationEvent",
        awaiting_validation_payload([(item_id, 2)]).encode(),
    )
    assert len(event_bus.published) == 1
    published = event_bus.published[0]
    assert isinstance(published, OrderStockConfirmedIntegrationEvent)
    assert json.loads(published.to_json())["OrderId"] == 42


async def test_awaiting_validation_rejects_when_stock_low(seeded_session_factory, event_bus):
    item_id = await first_item_id(seeded_session_factory)
    consumers = CatalogEventConsumers(seeded_session_factory, event_bus)
    await consumers.subscribe_all()
    await event_bus.deliver(
        "OrderStatusChangedToAwaitingValidationIntegrationEvent",
        awaiting_validation_payload([(item_id, 1000)]).encode(),
    )
    assert len(event_bus.published) == 1
    payload = json.loads(event_bus.published[0].to_json())
    assert payload["OrderStockItems"] == [{"ProductId": item_id, "HasStock": False}]


async def test_paid_removes_stock_once_despite_duplicate_delivery(seeded_session_factory, event_bus):
    item_id = await first_item_id(seeded_session_factory)
    consumers = CatalogEventConsumers(seeded_session_factory, event_bus)
    await consumers.subscribe_all()
    event_id = uuid.uuid4()
    body = json.dumps(
        {
            "OrderId": 42,
            "OrderStatus": "paid",
            "BuyerName": "alice@eshop",
            "OrderStockItems": [{"ProductId": item_id, "Units": 5}],
            "Id": str(event_id),
            "CreationDate": "2020-01-02T03:04:05.678Z",
        }
    ).encode()
    event_name = "OrderStatusChangedToPaidIntegrationEvent"
    await event_bus.deliver(event_name, body)
    await event_bus.deliver(event_name, body)  # duplicate delivery

    async with seeded_session_factory() as session:
        stored = (await session.execute(select(CatalogItem).where(CatalogItem.Id == item_id))).scalar_one()
        assert stored.AvailableStock == 95  # seeded 100 minus 5, applied exactly once


async def test_awaiting_validation_duplicate_publishes_once(seeded_session_factory, event_bus):
    item_id = await first_item_id(seeded_session_factory)
    consumers = CatalogEventConsumers(seeded_session_factory, event_bus)
    await consumers.subscribe_all()
    event_id = uuid.uuid4()
    body = awaiting_validation_payload([(item_id, 1)], event_id).encode()
    await event_bus.deliver("OrderStatusChangedToAwaitingValidationIntegrationEvent", body)
    await event_bus.deliver("OrderStatusChangedToAwaitingValidationIntegrationEvent", body)
    assert len(event_bus.published) == 1
