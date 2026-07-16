"""Integration-event handlers: forward each order-status event to the buyer's
room as ``UpdatedOrderState { orderId, status }``, mirroring the .NET handlers'
``Clients.Group(BuyerName).SendAsync("UpdatedOrderState", { OrderId, Status })``."""

from __future__ import annotations

import asyncio
import contextlib
import time

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


async def subscribe_all(
    bus: EventBus,
    hub: NotificationHub,
    timeout_seconds: float = 120.0,
    retry_delay_seconds: float = 3.0,
) -> None:
    """Subscribe to all order-status events and start consuming.

    The broker may not accept connections yet when the container starts
    (compose has no readiness ordering), so connection failures are retried —
    like the .NET persistent connection's retry policy — with the subscription
    registry rolled back between attempts to avoid duplicate handlers.
    """
    handler = make_handler(hub)
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            for event_type in ORDER_STATUS_EVENTS:
                await bus.subscribe(event_type, handler)
            await bus.start_consuming()
            return
        except Exception:
            for event_type in ORDER_STATUS_EVENTS:
                with contextlib.suppress(Exception):
                    await bus.unsubscribe(event_type, handler)
            if time.monotonic() >= deadline:
                raise
            logger.warning("event_bus_unavailable_retrying", delay=retry_delay_seconds)
            await asyncio.sleep(retry_delay_seconds)
