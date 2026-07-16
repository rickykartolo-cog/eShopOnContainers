"""Catalog integration events, field-for-field ports of the .NET classes.

Serialization is Newtonsoft-compatible via ``eshop_common.events`` and asserted
byte-for-byte against the golden artifacts in ``contracts/events/``.
"""

from __future__ import annotations

from decimal import Decimal

from eshop_common.events import IntegrationEvent
from eshop_common.outbox import register_event_type
from pydantic import BaseModel, ConfigDict, Field


@register_event_type
class ProductPriceChangedIntegrationEvent(IntegrationEvent):
    product_id: int = Field(alias="ProductId")
    new_price: Decimal = Field(alias="NewPrice")
    old_price: Decimal = Field(alias="OldPrice")


@register_event_type
class OrderStockConfirmedIntegrationEvent(IntegrationEvent):
    order_id: int = Field(alias="OrderId")


class ConfirmedOrderStockItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product_id: int = Field(alias="ProductId")
    has_stock: bool = Field(alias="HasStock")


@register_event_type
class OrderStockRejectedIntegrationEvent(IntegrationEvent):
    order_id: int = Field(alias="OrderId")
    order_stock_items: list[ConfirmedOrderStockItem] = Field(alias="OrderStockItems")


class OrderStockItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product_id: int = Field(alias="ProductId")
    units: int = Field(alias="Units")


class OrderStatusChangedToAwaitingValidationIntegrationEvent(IntegrationEvent):
    """Consumed copy: the Catalog handler reads ``OrderId`` and ``OrderStockItems``
    only (extra producer fields such as ``OrderStatus``/``BuyerName`` are ignored,
    matching Newtonsoft's tolerant deserialization into the consumer class)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    order_id: int = Field(alias="OrderId")
    order_stock_items: list[OrderStockItem] = Field(alias="OrderStockItems")


class OrderStatusChangedToPaidIntegrationEvent(IntegrationEvent):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    order_id: int = Field(alias="OrderId")
    order_stock_items: list[OrderStockItem] = Field(alias="OrderStockItems")
