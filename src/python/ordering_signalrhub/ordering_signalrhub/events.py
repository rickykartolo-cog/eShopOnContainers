"""The six order-status integration events consumed by the hub.

Field names, casing, and order mirror the .NET classes in
``src/Services/Ordering/Ordering.SignalrHub/IntegrationEvents/Events`` and the
golden JSON in ``contracts/events``.
"""

from __future__ import annotations

from eshop_common.events import IntegrationEvent
from pydantic import BaseModel, ConfigDict, Field


class OrderStockItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product_id: int = Field(alias="ProductId")
    units: int = Field(alias="Units")


class OrderStatusChangedToSubmittedIntegrationEvent(IntegrationEvent):
    order_id: int = Field(alias="OrderId")
    order_status: str = Field(alias="OrderStatus")
    buyer_name: str = Field(alias="BuyerName")


class OrderStatusChangedToAwaitingValidationIntegrationEvent(IntegrationEvent):
    order_id: int = Field(alias="OrderId")
    order_status: str = Field(alias="OrderStatus")
    buyer_name: str = Field(alias="BuyerName")
    order_stock_items: list[OrderStockItem] = Field(default_factory=list, alias="OrderStockItems")


class OrderStatusChangedToStockConfirmedIntegrationEvent(IntegrationEvent):
    order_id: int = Field(alias="OrderId")
    order_status: str = Field(alias="OrderStatus")
    buyer_name: str = Field(alias="BuyerName")


class OrderStatusChangedToPaidIntegrationEvent(IntegrationEvent):
    order_id: int = Field(alias="OrderId")
    order_status: str = Field(alias="OrderStatus")
    buyer_name: str = Field(alias="BuyerName")
    order_stock_items: list[OrderStockItem] = Field(default_factory=list, alias="OrderStockItems")


class OrderStatusChangedToShippedIntegrationEvent(IntegrationEvent):
    order_id: int = Field(alias="OrderId")
    order_status: str = Field(alias="OrderStatus")
    buyer_name: str = Field(alias="BuyerName")


class OrderStatusChangedToCancelledIntegrationEvent(IntegrationEvent):
    order_id: int = Field(alias="OrderId")
    order_status: str = Field(alias="OrderStatus")
    buyer_name: str = Field(alias="BuyerName")


ORDER_STATUS_EVENTS: tuple[type[IntegrationEvent], ...] = (
    OrderStatusChangedToSubmittedIntegrationEvent,
    OrderStatusChangedToAwaitingValidationIntegrationEvent,
    OrderStatusChangedToStockConfirmedIntegrationEvent,
    OrderStatusChangedToPaidIntegrationEvent,
    OrderStatusChangedToShippedIntegrationEvent,
    OrderStatusChangedToCancelledIntegrationEvent,
)
