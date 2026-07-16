"""Port of ``GracePeriodManagerService``: poll every ``CheckUpdateTime`` ms for
submitted orders older than ``GracePeriodTime`` minutes and publish
``GracePeriodConfirmedIntegrationEvent`` for each (direct publish, no outbox,
matching the .NET background service)."""

from __future__ import annotations

import asyncio

import structlog
from eshop_common.eventbus.base import EventBus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from ordering_backgroundtasks.events import GracePeriodConfirmedIntegrationEvent

logger = structlog.get_logger(__name__)

CONFIRMED_GRACE_PERIOD_ORDERS_SQL = text(
    """SELECT Id FROM ordering.orders
        WHERE DATEDIFF(minute, OrderDate, GETDATE()) >= :GracePeriodTime
        AND OrderStatusId = 1"""
)


class GracePeriodManager:
    def __init__(
        self,
        engine: AsyncEngine,
        event_bus: EventBus,
        grace_period_time: int,
        check_update_time_ms: int,
    ) -> None:
        self._engine = engine
        self._event_bus = event_bus
        self._grace_period_time = grace_period_time
        self._check_update_time_ms = check_update_time_ms

    async def run(self) -> None:
        logger.debug("grace_period_manager_starting")
        while True:
            await self.check_confirmed_grace_period_orders()
            await asyncio.sleep(self._check_update_time_ms / 1000)

    async def check_confirmed_grace_period_orders(self) -> None:
        logger.debug("checking_confirmed_grace_period_orders")
        for order_id in await self._get_confirmed_grace_period_orders():
            event = GracePeriodConfirmedIntegrationEvent(OrderId=order_id)
            logger.info("publishing_integration_event", event_id=str(event.id), order_id=order_id)
            await self._event_bus.publish(event)

    async def _get_confirmed_grace_period_orders(self) -> list[int]:
        try:
            async with self._engine.connect() as conn:
                result = await conn.execute(
                    CONFIRMED_GRACE_PERIOD_ORDERS_SQL,
                    {"GracePeriodTime": self._grace_period_time},
                )
                return [row[0] for row in result]
        except Exception as exc:
            # The .NET service logs SqlException as critical and keeps polling.
            logger.critical("database_connection_failed", error=str(exc))
            return []
