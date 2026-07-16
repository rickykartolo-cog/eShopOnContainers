"""Integration event published by the grace-period manager (port of
``Ordering.BackgroundTasks.Events.GracePeriodConfirmedIntegrationEvent``)."""

from __future__ import annotations

from eshop_common.events import IntegrationEvent
from eshop_common.outbox import register_event_type
from pydantic import Field


@register_event_type
class GracePeriodConfirmedIntegrationEvent(IntegrationEvent):
    order_id: int = Field(alias="OrderId")
