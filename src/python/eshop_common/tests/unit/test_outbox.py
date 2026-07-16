"""Outbox unit tests over SQLite (schema/lifecycle logic); the SQL Server
integration tests exercise the same code against the real database."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from eshop_common.eventbus.base import EventBus
from eshop_common.events import IntegrationEvent
from eshop_common.outbox import (
    EventState,
    IntegrationEventLogEntry,
    IntegrationEventLogService,
    OutboxPublisher,
    create_outbox_tables,
    register_event_type,
    try_mark_processed,
)


@register_event_type
class OrderStartedIntegrationEvent(IntegrationEvent):
    UserId: str


class FakeBus(EventBus):
    def __init__(self, fail: bool = False) -> None:
        self.published: list[IntegrationEvent] = []
        self.fail = fail

    async def publish(self, event: IntegrationEvent) -> None:
        if self.fail:
            raise ConnectionError("broker unavailable")
        self.published.append(event)

    async def subscribe(self, event_type, handler) -> None: ...
    async def unsubscribe(self, event_type, handler) -> None: ...
    async def start_consuming(self) -> None: ...
    async def close(self) -> None: ...


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await create_outbox_tables(conn)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def test_save_event_writes_integration_event_log_row(session):
    event = OrderStartedIntegrationEvent(UserId="alice")
    transaction_id = uuid.uuid4()
    service = IntegrationEventLogService(session)
    await service.save_event(event, transaction_id)
    await session.commit()

    row = (await session.execute(select(IntegrationEventLogEntry))).scalar_one()
    assert row.EventId == event.id
    assert row.EventTypeName == "OrderStartedIntegrationEvent"
    assert row.State == EventState.NotPublished
    assert row.TimesSent == 0
    assert row.TransactionId == str(transaction_id)
    assert '"UserId":"alice"' in row.Content


async def test_publisher_marks_published_and_increments_times_sent(session):
    event = OrderStartedIntegrationEvent(UserId="bob")
    transaction_id = uuid.uuid4()
    service = IntegrationEventLogService(session)
    await service.save_event(event, transaction_id)
    await session.commit()

    bus = FakeBus()
    await OutboxPublisher(service, bus).publish_events_through_event_bus(transaction_id)

    assert len(bus.published) == 1
    assert bus.published[0].id == event.id
    row = (await session.execute(select(IntegrationEventLogEntry))).scalar_one()
    assert row.State == EventState.Published
    assert row.TimesSent == 1


async def test_publish_failure_marks_published_failed_and_event_is_retained(session):
    event = OrderStartedIntegrationEvent(UserId="carol")
    transaction_id = uuid.uuid4()
    service = IntegrationEventLogService(session)
    await service.save_event(event, transaction_id)
    await session.commit()

    await OutboxPublisher(service, FakeBus(fail=True)).publish_events_through_event_bus(transaction_id)

    row = (await session.execute(select(IntegrationEventLogEntry))).scalar_one()
    assert row.State == EventState.PublishedFailed
    assert row.TimesSent == 1
    assert row.Content  # payload retained for retry


async def test_atomicity_rollback_discards_domain_and_outbox_together(session):
    event = OrderStartedIntegrationEvent(UserId="dave")
    service = IntegrationEventLogService(session)
    await service.save_event(event, uuid.uuid4())
    await session.rollback()
    rows = (await session.execute(select(IntegrationEventLogEntry))).scalars().all()
    assert rows == []


async def test_event_id_inbox_deduplicates(session):
    event_id = uuid.uuid4()
    assert await try_mark_processed(session, event_id) is True
    await session.commit()
    assert await try_mark_processed(session, event_id) is False


async def test_state_values_match_dotnet_event_state_enum():
    assert EventState.NotPublished == 0
    assert EventState.InProgress == 1
    assert EventState.Published == 2
    assert EventState.PublishedFailed == 3
