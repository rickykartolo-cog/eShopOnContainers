"""Integration-event handlers: forward each order-status event to the buyer's
room as ``UpdatedOrderState { orderId, status }``, mirroring the .NET handlers'
``Clients.Group(BuyerName).SendAsync("UpdatedOrderState", { OrderId, Status })``."""

from __future__ import annotations

import structlog
from eshop_common.eventbus.base import EventBus

from ordering_signalrhub.events import ORDER_STATUS_EVENTS
from ordering_signalrhub.hub import NotificationHub

logger = structlog.get_logger(__name__)


def make_handler(hub: NotificationHub):
    async def handle(event) -> None:
        logger.info(
            "handling_integration_event",
            event_id=str(event.id),
            event_name=type(event).event_name(),
            order_id=event.order_id,
            status=event.order_status,
        )
        await hub.send_order_status(event.buyer_name, event.order_id, event.order_status)

    return handle


async def subscribe_all(bus: EventBus, hub: NotificationHub) -> None:
    handler = make_handler(hub)
    for event_type in ORDER_STATUS_EVENTS:
        await bus.subscribe(event_type, handler)
    await bus.start_consuming()
