"""Integration-event consumer, port of the .NET
``OrderStatusChangedToStockConfirmedIntegrationEventHandler``.

Consume ``OrderStatusChangedToStockConfirmedIntegrationEvent`` and simulate the
payment against the ``PaymentSucceeded`` toggle: publish
``OrderPaymentSucceededIntegrationEvent`` when true, otherwise
``OrderPaymentFailedIntegrationEvent``, carrying the same ``OrderId``.

Duplicate delivery produces no additional side effects (§6.3.7): Payment is
stateless (no database), so an in-process bounded event-``Id`` inbox skips
redeliveries of an already-handled event. Ordering additionally remains safe
because its ``SetPaymentStatus`` transitions are monotonic (only applied from
``stockconfirmed``). The external event contract is unchanged.
"""

from __future__ import annotations

from collections import OrderedDict

import structlog
from eshop_common.eventbus.base import EventBus

from payment_api.events import (
    OrderPaymentFailedIntegrationEvent,
    OrderPaymentSucceededIntegrationEvent,
    OrderStatusChangedToStockConfirmedIntegrationEvent,
)
from payment_api.settings import PaymentSettings

logger = structlog.get_logger(__name__)

_INBOX_MAX_SIZE = 4096


class PaymentEventConsumers:
    def __init__(self, settings: PaymentSettings, event_bus: EventBus) -> None:
        self._settings = settings
        self._event_bus = event_bus
        self._inbox: OrderedDict[str, None] = OrderedDict()

    async def subscribe_all(self) -> None:
        await self._event_bus.subscribe(
            OrderStatusChangedToStockConfirmedIntegrationEvent, self.on_stock_confirmed
        )

    def _try_mark_processed(self, event_id: str) -> bool:
        if event_id in self._inbox:
            return False
        self._inbox[event_id] = None
        while len(self._inbox) > _INBOX_MAX_SIZE:
            self._inbox.popitem(last=False)
        return True

    async def on_stock_confirmed(self, event) -> None:
        assert isinstance(event, OrderStatusChangedToStockConfirmedIntegrationEvent)
        if not self._try_mark_processed(str(event.id)):
            logger.info("duplicate_event_skipped", event_id=str(event.id))
            return

        logger.info("handling_integration_event", event_id=str(event.id), order_id=event.order_id)

        # Business feature comment:
        # When OrderStatusChangedToStockConfirmed Integration Event is handled.
        # Here we're simulating that we'd be performing the payment against any payment gateway
        # Instead of a real payment we just take the env. var to simulate the payment
        # The payment can be successful or it can fail

        if self._settings.payment_succeeded:
            order_payment_event = OrderPaymentSucceededIntegrationEvent(OrderId=event.order_id)
        else:
            order_payment_event = OrderPaymentFailedIntegrationEvent(OrderId=event.order_id)

        logger.info(
            "publishing_integration_event",
            event_id=str(order_payment_event.id),
            event_name=type(order_payment_event).event_name(),
            order_id=event.order_id,
        )
        await self._event_bus.publish(order_payment_event)
