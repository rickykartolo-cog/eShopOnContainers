"""Payment integration events, field-for-field ports of the .NET classes in
``Payment.API/IntegrationEvents/Events``.

Serialization is Newtonsoft-compatible via ``eshop_common.events`` and asserted
byte-for-byte against the golden artifacts in ``contracts/events/``.
"""

from __future__ import annotations

from eshop_common.events import IntegrationEvent
from pydantic import ConfigDict, Field


class OrderStatusChangedToStockConfirmedIntegrationEvent(IntegrationEvent):
    """Consumed copy: the Payment handler reads ``OrderId`` only (extra producer
    fields such as ``OrderStatus``/``BuyerName`` are ignored, matching
    Newtonsoft's tolerant deserialization into the consumer class)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    order_id: int = Field(alias="OrderId")


class OrderPaymentSucceededIntegrationEvent(IntegrationEvent):
    order_id: int = Field(alias="OrderId")


class OrderPaymentFailedIntegrationEvent(IntegrationEvent):
    order_id: int = Field(alias="OrderId")
