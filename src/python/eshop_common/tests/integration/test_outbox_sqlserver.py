"""Outbox tests against real SQL Server: same-transaction atomicity, state
lifecycle over the ``IntegrationEventLog`` table, and event-Id deduplication."""

import uuid

import pytest
from sqlalchemy import select, text

from eshop_common.eventbus.base import EventBus
from eshop_common.events import IntegrationEvent
from eshop_common.outbox import (
    EventState,
    IntegrationEventLogEntry,
    IntegrationEventLogService,
    OutboxPublisher,
    register_event_type,
    try_mark_processed,
)

pytestmark = pytest.mark.integration


@register_event_type
class OrderStatusChangedToPaidIntegrationEvent(IntegrationEvent):
    OrderId: int = 0


class RecordingBus(EventBus):
    def __init__(self, fail: bool = False) -> None:
        self.published: list[IntegrationEvent] = []
        self.fail = fail

    async def publish(self, event: IntegrationEvent) -> None:
        if self.fail:
            raise ConnectionError("broker down")
        self.published.append(event)

    async def subscribe(self, event_type, handler) -> None: ...
    async def unsubscribe(self, event_type, handler) -> None: ...
    async def start_consuming(self) -> None: ...
    async def close(self) -> None: ...


async def test_integration_event_log_schema_columns(sql_engine, sql_session):
    result = await sql_session.execute(
        text(
            "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = 'IntegrationEventLog' ORDER BY COLUMN_NAME"
        )
    )
    columns = {row[0] for row in result}
    assert {
        "EventId",
        "EventTypeName",
        "State",
        "TimesSent",
        "CreationTime",
        "Content",
        "TransactionId",
    } <= columns


async def test_domain_write_and_outbox_insert_share_transaction(sql_session):
    await sql_session.execute(
        text("IF OBJECT_ID('dbo.__domain_rows') IS NOT NULL DROP TABLE dbo.__domain_rows")
    )
    await sql_session.execute(text("CREATE TABLE dbo.__domain_rows (Id INT PRIMARY KEY)"))
    await sql_session.commit()

    event = OrderStatusChangedToPaidIntegrationEvent(OrderId=99)
    service = IntegrationEventLogService(sql_session)
    await sql_session.execute(text("INSERT INTO dbo.__domain_rows VALUES (99)"))
    await service.save_event(event, uuid.uuid4())
    await sql_session.rollback()

    domain_count = (await sql_session.execute(text("SELECT COUNT(*) FROM dbo.__domain_rows"))).scalar_one()
    outbox_count = (
        await sql_session.execute(
            select(IntegrationEventLogEntry).where(IntegrationEventLogEntry.EventId == event.id)
        )
    ).scalars().all()
    assert domain_count == 0
    assert outbox_count == []
    await sql_session.execute(text("DROP TABLE dbo.__domain_rows"))
    await sql_session.commit()


async def test_full_lifecycle_not_published_to_published(sql_session):
    event = OrderStatusChangedToPaidIntegrationEvent(OrderId=1)
    transaction_id = uuid.uuid4()
    service = IntegrationEventLogService(sql_session)
    await service.save_event(event, transaction_id)
    await sql_session.commit()

    bus = RecordingBus()
    await OutboxPublisher(service, bus).publish_events_through_event_bus(transaction_id)
    row = (
        await sql_session.execute(
            select(IntegrationEventLogEntry).where(IntegrationEventLogEntry.EventId == event.id)
        )
    ).scalar_one()
    assert row.State == EventState.Published
    assert row.TimesSent == 1
    assert len(bus.published) == 1


async def test_failed_publish_retained_as_published_failed(sql_session):
    event = OrderStatusChangedToPaidIntegrationEvent(OrderId=2)
    transaction_id = uuid.uuid4()
    service = IntegrationEventLogService(sql_session)
    await service.save_event(event, transaction_id)
    await sql_session.commit()

    await OutboxPublisher(service, RecordingBus(fail=True)).publish_events_through_event_bus(transaction_id)
    row = (
        await sql_session.execute(
            select(IntegrationEventLogEntry).where(IntegrationEventLogEntry.EventId == event.id)
        )
    ).scalar_one()
    assert row.State == EventState.PublishedFailed
    assert row.Content


async def test_duplicate_delivery_no_additional_side_effects(sql_session):
    event_id = uuid.uuid4()
    side_effects = 0
    for _ in range(3):
        if await try_mark_processed(sql_session, event_id):
            side_effects += 1
            await sql_session.commit()
    assert side_effects == 1
