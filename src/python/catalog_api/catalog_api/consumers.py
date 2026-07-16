"""Integration-event consumers, ports of the .NET handlers.

- ``OrderStatusChangedToAwaitingValidationIntegrationEvent`` → stock validation →
  publish ``OrderStockConfirmed``/``OrderStockRejected`` through the outbox
  (atomic with the catalog context changes, matching
  ``SaveEventAndCatalogContextChangesAsync``).
- ``OrderStatusChangedToPaidIntegrationEvent`` → ``RemoveStock`` per item.

Duplicate delivery produces no additional side effects (§6.3.7): each inbound
event ``Id`` is recorded in the existing ``IntegrationEventLog`` table (primary
key ``EventId``) inside the same transaction as the side effects, so a redelivery
hits the PK and is skipped. No schema change: the frozen dump stays intact, and
the rows are inert to the .NET outbox (which only reads by ``TransactionId``).
"""

from __future__ import annotations

from datetime import UTC, datetime

import structlog
from eshop_common.eventbus.base import EventBus
from eshop_common.events import IntegrationEvent
from eshop_common.outbox import EventState, IntegrationEventLogEntry
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from catalog_api.events import (
    ConfirmedOrderStockItem,
    OrderStatusChangedToAwaitingValidationIntegrationEvent,
    OrderStatusChangedToPaidIntegrationEvent,
    OrderStockConfirmedIntegrationEvent,
    OrderStockRejectedIntegrationEvent,
)
from catalog_api.integration import CatalogIntegrationEventService
from catalog_api.models import CatalogItem

logger = structlog.get_logger(__name__)


async def _try_mark_processed(session: AsyncSession, event: IntegrationEvent) -> bool:
    """Record the inbound event in IntegrationEventLog (PK EventId) within the
    consumer's transaction; returns False when it was already processed."""
    session.add(
        IntegrationEventLogEntry(
            EventId=event.id,
            EventTypeName=type(event).event_name(),
            State=int(EventState.Published),
            TimesSent=0,
            CreationTime=datetime.now(UTC).replace(tzinfo=None),
            Content=event.to_json(),
            TransactionId=None,
        )
    )
    try:
        await session.flush()
        return True
    except IntegrityError:
        await session.rollback()
        return False


class CatalogEventConsumers:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], event_bus: EventBus) -> None:
        self._session_factory = session_factory
        self._event_bus = event_bus

    async def subscribe_all(self) -> None:
        await self._event_bus.subscribe(
            OrderStatusChangedToAwaitingValidationIntegrationEvent, self.on_awaiting_validation
        )
        await self._event_bus.subscribe(OrderStatusChangedToPaidIntegrationEvent, self.on_paid)

    async def on_awaiting_validation(self, event) -> None:
        assert isinstance(event, OrderStatusChangedToAwaitingValidationIntegrationEvent)
        async with self._session_factory() as session:
            if not await _try_mark_processed(session, event):
                logger.info("duplicate_event_skipped", event_id=str(event.id))
                return
            confirmed: list[ConfirmedOrderStockItem] = []
            for stock_item in event.order_stock_items:
                catalog_item = (
                    await session.execute(select(CatalogItem).where(CatalogItem.Id == stock_item.product_id))
                ).scalar_one()
                has_stock = catalog_item.AvailableStock >= stock_item.units
                confirmed.append(ConfirmedOrderStockItem(ProductId=catalog_item.Id, HasStock=has_stock))

            if any(not item.has_stock for item in confirmed):
                result_event = OrderStockRejectedIntegrationEvent(OrderId=event.order_id, OrderStockItems=confirmed)
            else:
                result_event = OrderStockConfirmedIntegrationEvent(OrderId=event.order_id)

            integration = CatalogIntegrationEventService(session, self._event_bus)
            await integration.save_event_and_catalog_context_changes(result_event)
            await integration.publish_through_event_bus(result_event)

    async def on_paid(self, event) -> None:
        assert isinstance(event, OrderStatusChangedToPaidIntegrationEvent)
        async with self._session_factory() as session:
            if not await _try_mark_processed(session, event):
                logger.info("duplicate_event_skipped", event_id=str(event.id))
                return
            for stock_item in event.order_stock_items:
                catalog_item = (
                    await session.execute(select(CatalogItem).where(CatalogItem.Id == stock_item.product_id))
                ).scalar_one()
                catalog_item.remove_stock(stock_item.units)
            await session.commit()
