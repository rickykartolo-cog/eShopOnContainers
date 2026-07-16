"""Webhooks-side copies of the consumed integration events, field-for-field
ports of the classes under ``Webhooks.API/IntegrationEvents``.

The webhook callback ``Payload`` is the Newtonsoft serialization of the
consumer-side class (only the fields it declares), so extra producer fields are
dropped exactly like Newtonsoft's tolerant deserialization into these copies.
"""

from __future__ import annotations

from decimal import Decimal

from eshop_common.events import IntegrationEvent
from pydantic import BaseModel, ConfigDict, Field


class ProductPriceChangedIntegrationEvent(IntegrationEvent):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    product_id: int = Field(alias="ProductId")
    new_price: Decimal = Field(alias="NewPrice")
    old_price: Decimal = Field(alias="OldPrice")


class OrderStatusChangedToShippedIntegrationEvent(IntegrationEvent):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    order_id: int = Field(alias="OrderId")
    order_status: str = Field(alias="OrderStatus")
    buyer_name: str = Field(alias="BuyerName")


class OrderStockItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product_id: int = Field(alias="ProductId")
    units: int = Field(alias="Units")


class OrderStatusChangedToPaidIntegrationEvent(IntegrationEvent):
    """Webhooks' copy declares ``OrderId`` and ``OrderStockItems`` only; the
    producer's extra ``OrderStatus``/``BuyerName`` fields are ignored."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    order_id: int = Field(alias="OrderId")
    order_stock_items: list[OrderStockItem] = Field(alias="OrderStockItems")
