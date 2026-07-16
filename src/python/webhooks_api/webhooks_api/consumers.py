"""Integration-event consumers, ports of the .NET handlers.

- ``ProductPriceChangedIntegrationEvent`` → intentionally a no-op (the .NET
  handler body is empty); subscribing keeps the queue binding identical.
- ``OrderStatusChangedToShippedIntegrationEvent`` → POST ``WebhookData`` (type
  ``OrderShipped``) to every ``OrderShipped`` subscription.
- ``OrderStatusChangedToPaidIntegrationEvent`` → POST ``WebhookData`` (type
  ``OrderPaid``) to every ``OrderPaid`` subscription.

Handlers are read-only against the database and keep the .NET at-least-once
semantics: a duplicate broker delivery repeats the outbound POST (exactly as
the .NET service does), never corrupts state, and never multiplies deliveries
for a single receipt. The frozen Webhooks schema has no outbox/inbox table, so
no event-``Id`` inbox is added (a schema change is prohibited); the delivery
contract to subscribers remains at-least-once per event receipt.
"""

from __future__ import annotations

import structlog
from eshop_common.eventbus.base import EventBus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from webhooks_api.events import (
    OrderStatusChangedToPaidIntegrationEvent,
    OrderStatusChangedToShippedIntegrationEvent,
    ProductPriceChangedIntegrationEvent,
)
from webhooks_api.models import WebhookSubscription, WebhookType
from webhooks_api.sender import WebhookData, WebhooksSender

logger = structlog.get_logger(__name__)


class WebhooksEventConsumers:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], sender: WebhooksSender) -> None:
        self._session_factory = session_factory
        self._sender = sender

    async def subscribe_all(self, event_bus: EventBus) -> None:
        await event_bus.subscribe(ProductPriceChangedIntegrationEvent, self.on_product_price_changed)
        await event_bus.subscribe(OrderStatusChangedToShippedIntegrationEvent, self.on_order_shipped)
        await event_bus.subscribe(OrderStatusChangedToPaidIntegrationEvent, self.on_order_paid)

    async def on_product_price_changed(self, event) -> None:
        # Parity with the .NET handler, whose body is empty.
        assert isinstance(event, ProductPriceChangedIntegrationEvent)

    async def on_order_shipped(self, event) -> None:
        assert isinstance(event, OrderStatusChangedToShippedIntegrationEvent)
        await self._notify(WebhookType.OrderShipped, event)

    async def on_order_paid(self, event) -> None:
        assert isinstance(event, OrderStatusChangedToPaidIntegrationEvent)
        await self._notify(WebhookType.OrderPaid, event)

    async def _notify(self, hook_type: WebhookType, event) -> None:
        subscriptions = await self._subscriptions_of_type(hook_type)
        logger.info(
            "webhook_event_received",
            event_name=type(event).event_name(),
            subscriptions=len(subscriptions),
        )
        data = WebhookData(hook_type, event)
        await self._sender.send_all(subscriptions, data)

    async def _subscriptions_of_type(self, hook_type: WebhookType) -> list[WebhookSubscription]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(WebhookSubscription).where(WebhookSubscription.Type == int(hook_type))
                )
            ).scalars().all()
            return list(rows)
