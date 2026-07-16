"""Ports of ``OrderingIntegrationEventService``, ``TransactionBehaviour`` and
``OrderingContext.SaveEntitiesAsync``/``DispatchDomainEventsAsync``.

Command pipeline (per command, mirroring ``TransactionBehaviour``):
1. handlers mutate aggregates and enqueue outbox rows in ONE session transaction;
2. domain events dispatch sequentially BEFORE the save completes;
3. the transaction commits atomically (aggregate + outbox);
4. pending integration events publish through the bus only AFTER commit, with
   ``InProgress`` -> ``Published``/``PublishedFailed`` state tracking.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import structlog
from eshop_common.eventbus.base import EventBus
from eshop_common.events import IntegrationEvent
from eshop_common.outbox import IntegrationEventLogService, OutboxPublisher
from sqlalchemy.ext.asyncio import AsyncSession

from ordering_api.mediator import Mediator, SupportsValidation
from ordering_api.models import DomainEntity

logger = structlog.get_logger(__name__)

EVENT_NAMESPACE = "Ordering.API.Application.IntegrationEvents.Events"


class OrderingIntegrationEventService:
    def __init__(
        self, session: AsyncSession, event_bus: EventBus, transaction_id: uuid.UUID
    ) -> None:
        self._session = session
        self._log_service = IntegrationEventLogService(session, event_namespace=EVENT_NAMESPACE)
        self._publisher = OutboxPublisher(self._log_service, event_bus)
        self.transaction_id = transaction_id

    async def add_and_save_event(self, event: IntegrationEvent) -> None:
        logger.info(
            "enqueuing_integration_event",
            event_id=str(event.id),
            event_name=type(event).event_name(),
        )
        await self._log_service.save_event(event, self.transaction_id)

    async def publish_events_through_event_bus(self) -> None:
        await self._publisher.publish_events_through_event_bus(self.transaction_id)


@dataclass
class Identity:
    """Port of ``IIdentityService`` (sub claim + user name)."""

    user_id: str | None = None
    user_name: str | None = None


@dataclass
class CommandContext:
    """Ambient services a command/domain-event handler receives (DI equivalent)."""

    session: AsyncSession
    mediator: Mediator
    integration_events: OrderingIntegrationEventService
    identity: Identity = field(default_factory=Identity)


async def save_entities(ctx: CommandContext) -> bool:
    """Port of ``SaveEntitiesAsync``: dispatch domain events, then persist."""
    await dispatch_domain_events(ctx)
    await ctx.session.flush()
    return True


async def dispatch_domain_events(ctx: CommandContext) -> None:
    """Port of ``MediatorExtension.DispatchDomainEventsAsync``: collect events from
    tracked entities, clear, then publish sequentially."""
    seen: set[int] = set()
    entities = []
    for entity in list(ctx.session.new) + list(ctx.session):
        if isinstance(entity, DomainEntity) and entity.domain_events and id(entity) not in seen:
            seen.add(id(entity))
            entities.append(entity)
    domain_events = [event for entity in entities for event in entity.domain_events]
    for entity in entities:
        entity.clear_domain_events()
    for event in domain_events:
        await ctx.mediator.publish(event, ctx)


async def execute_command_transaction(
    session: AsyncSession,
    mediator: Mediator,
    event_bus: EventBus,
    command: SupportsValidation,
    identity: Identity | None = None,
) -> object:
    """Port of ``TransactionBehaviour``: one transaction per command, publish after commit."""
    transaction_id = uuid.uuid4()
    integration_events = OrderingIntegrationEventService(session, event_bus, transaction_id)
    ctx = CommandContext(
        session=session,
        mediator=mediator,
        integration_events=integration_events,
        identity=identity or Identity(),
    )
    result = await mediator.send(command, ctx)
    await session.commit()
    await integration_events.publish_events_through_event_bus()
    return result
