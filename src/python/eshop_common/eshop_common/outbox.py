"""Transactional outbox preserving the .NET ``IntegrationEventLog`` schema.

Table ``IntegrationEventLog`` columns and states match
``Microsoft.eShopOnContainers.BuildingBlocks.IntegrationEventLogEF`` exactly:
``EventId`` (GUID PK), ``EventTypeName``, ``State`` (int), ``TimesSent``,
``CreationTime``, ``Content`` (Newtonsoft JSON), ``TransactionId``.

Also provides an event-``Id`` inbox (``ProcessedIntegrationEvents``) for
consumer-side deduplication; the inbox table is additive and does not change
any existing contract.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import DateTime, Integer, String, Uuid, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from eshop_common.eventbus.base import EventBus
from eshop_common.events import IntegrationEvent

logger = structlog.get_logger(__name__)


class EventState(enum.IntEnum):
    """Mirrors .NET ``EventStateEnum``."""

    NotPublished = 0
    InProgress = 1
    Published = 2
    PublishedFailed = 3


class OutboxBase(DeclarativeBase):
    pass


class IntegrationEventLogEntry(OutboxBase):
    __tablename__ = "IntegrationEventLog"

    EventId: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    EventTypeName: Mapped[str] = mapped_column(String, nullable=False)
    State: Mapped[int] = mapped_column(Integer, nullable=False)
    TimesSent: Mapped[int] = mapped_column(Integer, nullable=False)
    CreationTime: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    Content: Mapped[str] = mapped_column(String, nullable=False)
    TransactionId: Mapped[str | None] = mapped_column(String, nullable=True)

    @property
    def event_type_short_name(self) -> str:
        return self.EventTypeName.split(".")[-1]


class ProcessedIntegrationEvent(OutboxBase):
    """Consumer-side inbox for event-Id deduplication (additive, Python services only)."""

    __tablename__ = "ProcessedIntegrationEvents"

    EventId: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    ProcessedTime: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class IntegrationEventLogService:
    """Port of ``IntegrationEventLogService`` working inside a caller-owned transaction."""

    def __init__(self, session: AsyncSession, event_namespace: str = "") -> None:
        self._session = session
        self._event_namespace = event_namespace

    def _full_type_name(self, event: IntegrationEvent) -> str:
        name = type(event).event_name()
        return f"{self._event_namespace}.{name}" if self._event_namespace else name

    async def save_event(self, event: IntegrationEvent, transaction_id: str | uuid.UUID) -> None:
        """Insert the outbox entry inside the SAME transaction as the domain change."""
        entry = IntegrationEventLogEntry(
            EventId=event.id,
            EventTypeName=self._full_type_name(event),
            State=int(EventState.NotPublished),
            TimesSent=0,
            CreationTime=event.creation_date.astimezone(UTC).replace(tzinfo=None),
            Content=event.to_json(),
            TransactionId=str(transaction_id),
        )
        self._session.add(entry)

    async def retrieve_pending(self, transaction_id: str | uuid.UUID) -> list[IntegrationEventLogEntry]:
        result = await self._session.execute(
            select(IntegrationEventLogEntry)
            .where(
                IntegrationEventLogEntry.TransactionId == str(transaction_id),
                IntegrationEventLogEntry.State == int(EventState.NotPublished),
            )
            .order_by(IntegrationEventLogEntry.CreationTime)
        )
        return list(result.scalars())

    async def mark_in_progress(self, event_id: uuid.UUID) -> None:
        await self._update_state(event_id, EventState.InProgress, increment_times_sent=True)

    async def mark_published(self, event_id: uuid.UUID) -> None:
        await self._update_state(event_id, EventState.Published)

    async def mark_failed(self, event_id: uuid.UUID) -> None:
        await self._update_state(event_id, EventState.PublishedFailed)

    async def _update_state(
        self, event_id: uuid.UUID, state: EventState, increment_times_sent: bool = False
    ) -> None:
        values: dict = {"State": int(state)}
        if increment_times_sent:
            values["TimesSent"] = IntegrationEventLogEntry.TimesSent + 1
        await self._session.execute(
            update(IntegrationEventLogEntry)
            .where(IntegrationEventLogEntry.EventId == event_id)
            .values(**values)
        )
        await self._session.commit()


class OutboxPublisher:
    """Publish-after-commit flow matching ``SaveEventAndCatalogContextChangesAsync`` semantics:
    the domain change and outbox insert commit atomically; publication happens afterwards
    with per-event state tracking (InProgress -> Published / PublishedFailed)."""

    def __init__(self, log_service: IntegrationEventLogService, event_bus: EventBus) -> None:
        self._log = log_service
        self._bus = event_bus

    async def publish_events_through_event_bus(self, transaction_id: str | uuid.UUID) -> None:
        for entry in await self._log.retrieve_pending(transaction_id):
            event_id = entry.EventId
            try:
                await self._log.mark_in_progress(event_id)
                event = _resolve_event(entry)
                await self._bus.publish(event)
                await self._log.mark_published(event_id)
            except Exception:
                logger.error("publish_failed", event_id=str(event_id), exc_info=True)
                await self._log.mark_failed(event_id)


_EVENT_TYPES: dict[str, type[IntegrationEvent]] = {}


def register_event_type(event_type: type[IntegrationEvent]) -> type[IntegrationEvent]:
    """Register an event class so outbox entries can be re-materialized for publishing."""
    _EVENT_TYPES[event_type.event_name()] = event_type
    return event_type


def _resolve_event(entry: IntegrationEventLogEntry) -> IntegrationEvent:
    event_type = _EVENT_TYPES.get(entry.event_type_short_name)
    if event_type is None:
        raise LookupError(f"Integration event type '{entry.event_type_short_name}' is not registered")
    return event_type.from_json(entry.Content)


async def try_mark_processed(session: AsyncSession, event_id: uuid.UUID) -> bool:
    """Record an inbound event id; returns False when it was already processed.

    Call inside the same transaction as the consumer's side effects so duplicate
    delivery produces no additional side effects.
    """
    session.add(ProcessedIntegrationEvent(EventId=event_id, ProcessedTime=datetime.now(UTC).replace(tzinfo=None)))
    try:
        await session.flush()
        return True
    except IntegrityError:
        await session.rollback()
        return False


async def create_outbox_tables(connection: AsyncConnection) -> None:
    await connection.run_sync(OutboxBase.metadata.create_all)
