"""Ordering integration events, field-for-field ports of the .NET classes.

Serialization is Newtonsoft-compatible via ``eshop_common.events`` and asserted
byte-for-byte against the golden artifacts in ``contracts/events/``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from eshop_common.events import IntegrationEvent
from eshop_common.outbox import register_event_type
from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class OrderStockItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product_id: int = Field(alias="ProductId")
    units: int = Field(alias="Units")


class ConfirmedOrderStockItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product_id: int = Field(alias="ProductId")
    has_stock: bool = Field(alias="HasStock")


# --- Produced by Ordering.API (order state machine, §6.3) ---


@register_event_type
class OrderStartedIntegrationEvent(IntegrationEvent):
    user_id: str = Field(alias="UserId")


@register_event_type
class OrderStatusChangedToSubmittedIntegrationEvent(IntegrationEvent):
    order_id: int = Field(alias="OrderId")
    order_status: str = Field(alias="OrderStatus")
    buyer_name: str | None = Field(alias="BuyerName")


@register_event_type
class OrderStatusChangedToAwaitingValidationIntegrationEvent(IntegrationEvent):
    order_id: int = Field(alias="OrderId")
    order_status: str = Field(alias="OrderStatus")
    buyer_name: str | None = Field(alias="BuyerName")
    order_stock_items: list[OrderStockItem] = Field(alias="OrderStockItems")


@register_event_type
class OrderStatusChangedToStockConfirmedIntegrationEvent(IntegrationEvent):
    order_id: int = Field(alias="OrderId")
    order_status: str = Field(alias="OrderStatus")
    buyer_name: str | None = Field(alias="BuyerName")


@register_event_type
class OrderStatusChangedToPaidIntegrationEvent(IntegrationEvent):
    order_id: int = Field(alias="OrderId")
    order_status: str = Field(alias="OrderStatus")
    buyer_name: str | None = Field(alias="BuyerName")
    order_stock_items: list[OrderStockItem] = Field(alias="OrderStockItems")


@register_event_type
class OrderStatusChangedToShippedIntegrationEvent(IntegrationEvent):
    order_id: int = Field(alias="OrderId")
    order_status: str = Field(alias="OrderStatus")
    buyer_name: str | None = Field(alias="BuyerName")


@register_event_type
class OrderStatusChangedToCancelledIntegrationEvent(IntegrationEvent):
    order_id: int = Field(alias="OrderId")
    order_status: str = Field(alias="OrderStatus")
    buyer_name: str | None = Field(alias="BuyerName")


# --- Consumed by Ordering.API ---


class BasketItemData(BaseModel):
    """Bound from both PascalCase (integration events) and camelCase (HTTP draft
    body) JSON, like the case-insensitive Newtonsoft binder."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    id: str | None = Field(default=None, validation_alias=AliasChoices("Id", "id"), serialization_alias="Id")
    product_id: int = Field(validation_alias=AliasChoices("ProductId", "productId"), serialization_alias="ProductId")
    product_name: str | None = Field(
        default=None, validation_alias=AliasChoices("ProductName", "productName"), serialization_alias="ProductName"
    )
    unit_price: Decimal = Field(
        validation_alias=AliasChoices("UnitPrice", "unitPrice"), serialization_alias="UnitPrice"
    )
    old_unit_price: Decimal = Field(
        default=Decimal(0),
        validation_alias=AliasChoices("OldUnitPrice", "oldUnitPrice"),
        serialization_alias="OldUnitPrice",
    )
    quantity: int = Field(validation_alias=AliasChoices("Quantity", "quantity"), serialization_alias="Quantity")
    picture_url: str | None = Field(
        default=None, validation_alias=AliasChoices("PictureUrl", "pictureUrl"), serialization_alias="PictureUrl"
    )


class CustomerBasketData(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    buyer_id: str | None = Field(default=None, alias="BuyerId")
    items: list[BasketItemData] = Field(default_factory=list, alias="Items")


@register_event_type
class UserCheckoutAcceptedIntegrationEvent(IntegrationEvent):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    user_id: str = Field(alias="UserId")
    user_name: str | None = Field(default=None, alias="UserName")
    order_number: int = Field(default=0, alias="OrderNumber")
    city: str | None = Field(default=None, alias="City")
    street: str | None = Field(default=None, alias="Street")
    state: str | None = Field(default=None, alias="State")
    country: str | None = Field(default=None, alias="Country")
    zip_code: str | None = Field(default=None, alias="ZipCode")
    card_number: str | None = Field(default=None, alias="CardNumber")
    card_holder_name: str | None = Field(default=None, alias="CardHolderName")
    card_expiration: datetime = Field(alias="CardExpiration")
    card_security_number: str | None = Field(default=None, alias="CardSecurityNumber")
    card_type_id: int = Field(default=0, alias="CardTypeId")
    buyer: str | None = Field(default=None, alias="Buyer")
    request_id: uuid.UUID = Field(alias="RequestId")
    basket: CustomerBasketData = Field(alias="Basket")


@register_event_type
class GracePeriodConfirmedIntegrationEvent(IntegrationEvent):
    order_id: int = Field(alias="OrderId")


@register_event_type
class OrderStockConfirmedIntegrationEvent(IntegrationEvent):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    order_id: int = Field(alias="OrderId")


@register_event_type
class OrderStockRejectedIntegrationEvent(IntegrationEvent):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    order_id: int = Field(alias="OrderId")
    order_stock_items: list[ConfirmedOrderStockItem] = Field(alias="OrderStockItems")


@register_event_type
class OrderPaymentSucceededIntegrationEvent(IntegrationEvent):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    order_id: int = Field(alias="OrderId")


@register_event_type
class OrderPaymentFailedIntegrationEvent(IntegrationEvent):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    order_id: int = Field(alias="OrderId")
