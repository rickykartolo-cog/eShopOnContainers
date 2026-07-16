"""Basket integration events, field-for-field ports of the .NET classes.

Serialization is Newtonsoft-compatible via ``eshop_common.events`` and asserted
byte-for-byte against the golden artifacts in ``contracts/events/``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from eshop_common.events import IntegrationEvent
from eshop_common.outbox import register_event_type
from pydantic import ConfigDict, Field

from basket_api.models import CustomerBasket


@register_event_type
class UserCheckoutAcceptedIntegrationEvent(IntegrationEvent):
    """Published to Ordering on checkout; property order matches the .NET class
    declaration so the serialized JSON equals the golden byte-for-byte."""

    user_id: str | None = Field(alias="UserId")
    user_name: str | None = Field(alias="UserName")
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
    basket: CustomerBasket | None = Field(alias="Basket")


@register_event_type
class ProductPriceChangedIntegrationEvent(IntegrationEvent):
    """Consumed copy from Catalog (tolerant deserialization like Newtonsoft)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    product_id: int = Field(alias="ProductId")
    new_price: Decimal = Field(alias="NewPrice")
    old_price: Decimal = Field(alias="OldPrice")


@register_event_type
class OrderStartedIntegrationEvent(IntegrationEvent):
    """Consumed copy from Ordering."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    user_id: str | None = Field(alias="UserId")
