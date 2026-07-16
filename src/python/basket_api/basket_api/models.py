"""Basket models, field-for-field ports of the .NET ``CustomerBasket`` /
``BasketItem`` / ``BasketCheckout`` classes.

Two serialized layouts exist and must both be preserved:

- **Redis storage** uses ``JsonConvert.SerializeObject`` defaults (PascalCase),
  so Python-written entries stay interchangeable with .NET-written entries.
- **HTTP responses** use ASP.NET Core MVC + AddNewtonsoftJson (camelCase).

Request binding is tolerant like Newtonsoft: property-name matching is
case-insensitive and unknown members are ignored.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from eshop_common.events import dumps_newtonsoft, parse_newtonsoft_datetime
from pydantic import BaseModel, ConfigDict, Field


class BindingError(ValueError):
    """Model-binding failure: maps to the 400 ``JsonErrorResponse`` body."""

    def __init__(self, messages: list[str]) -> None:
        super().__init__("; ".join(messages))
        self.messages = messages


def _ci(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise BindingError(["The input does not contain any JSON tokens."])
    return {str(key).lower(): value for key, value in data.items()}


class BasketItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str | None = Field(default=None, alias="Id")
    product_id: int = Field(default=0, alias="ProductId")
    product_name: str | None = Field(default=None, alias="ProductName")
    unit_price: Decimal = Field(default=Decimal(0), alias="UnitPrice")
    old_unit_price: Decimal = Field(default=Decimal(0), alias="OldUnitPrice")
    quantity: int = Field(default=0, alias="Quantity")
    picture_url: str | None = Field(default=None, alias="PictureUrl")

    def validate_units(self) -> list[str]:
        """Port of ``BasketItem.Validate`` (IValidatableObject)."""
        return ["Invalid number of units"] if self.quantity < 1 else []

    @classmethod
    def from_loose(cls, data: Any) -> BasketItem:
        values = _ci(data)
        return cls(
            Id=values.get("id"),
            ProductId=int(values.get("productid") or 0),
            ProductName=values.get("productname"),
            UnitPrice=Decimal(str(values.get("unitprice") or 0)),
            OldUnitPrice=Decimal(str(values.get("oldunitprice") or 0)),
            Quantity=int(values.get("quantity") or 0),
            PictureUrl=values.get("pictureurl"),
        )

    def http_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "productId": self.product_id,
            "productName": self.product_name,
            "unitPrice": self.unit_price,
            "oldUnitPrice": self.old_unit_price,
            "quantity": self.quantity,
            "pictureUrl": self.picture_url,
        }


class CustomerBasket(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    buyer_id: str | None = Field(default=None, alias="BuyerId")
    items: list[BasketItem] = Field(default_factory=list, alias="Items")

    @classmethod
    def from_loose(cls, data: Any) -> CustomerBasket:
        values = _ci(data)
        items = values.get("items") or []
        if not isinstance(items, list):
            raise BindingError(["The input does not contain a valid Items array."])
        return cls(
            BuyerId=values.get("buyerid"),
            Items=[BasketItem.from_loose(item) for item in items],
        )

    @classmethod
    def from_redis_json(cls, payload: str | bytes) -> CustomerBasket:
        return cls.from_loose(json.loads(payload, parse_float=Decimal, parse_int=Decimal))

    def to_redis_json(self) -> str:
        """PascalCase Newtonsoft layout, identical to the .NET repository writes."""
        return dumps_newtonsoft(
            {
                "BuyerId": self.buyer_id,
                "Items": [
                    {
                        "Id": item.id,
                        "ProductId": _as_int(item.product_id),
                        "ProductName": item.product_name,
                        "UnitPrice": item.unit_price,
                        "OldUnitPrice": item.old_unit_price,
                        "Quantity": _as_int(item.quantity),
                        "PictureUrl": item.picture_url,
                    }
                    for item in self.items
                ],
            }
        )

    def http_payload(self) -> dict[str, Any]:
        return {"buyerId": self.buyer_id, "items": [item.http_payload() for item in self.items]}


def _as_int(value: Any) -> int:
    return int(value)


EMPTY_GUID = uuid.UUID(int=0)


class BasketCheckout(BaseModel):
    """Port of ``BasketCheckout`` with Newtonsoft-style tolerant binding."""

    model_config = ConfigDict(populate_by_name=True)

    city: str | None = None
    street: str | None = None
    state: str | None = None
    country: str | None = None
    zip_code: str | None = None
    card_number: str | None = None
    card_holder_name: str | None = None
    card_expiration: datetime = Field(default_factory=lambda: datetime(1, 1, 1, tzinfo=UTC))
    card_security_number: str | None = None
    card_type_id: int = 0
    buyer: str | None = None
    request_id: uuid.UUID = EMPTY_GUID

    @classmethod
    def from_loose(cls, data: Any) -> BasketCheckout:
        values = _ci(data)
        errors: list[str] = []
        card_expiration = datetime(1, 1, 1, tzinfo=UTC)
        raw_expiration = values.get("cardexpiration")
        if raw_expiration is not None:
            try:
                card_expiration = parse_newtonsoft_datetime(str(raw_expiration))
            except ValueError:
                errors.append(f"Could not convert string to DateTime: {raw_expiration}.")
        request_id = EMPTY_GUID
        raw_request_id = values.get("requestid")
        if raw_request_id is not None:
            try:
                request_id = uuid.UUID(str(raw_request_id))
            except ValueError:
                errors.append(f"Error converting value \"{raw_request_id}\" to type 'System.Guid'.")
        card_type_id = 0
        raw_card_type = values.get("cardtypeid")
        if raw_card_type is not None:
            try:
                card_type_id = int(raw_card_type)
            except (TypeError, ValueError):
                errors.append(f"Could not convert string to integer: {raw_card_type}.")
        if errors:
            raise BindingError(errors)
        return cls(
            city=values.get("city"),
            street=values.get("street"),
            state=values.get("state"),
            country=values.get("country"),
            zip_code=values.get("zipcode"),
            card_number=values.get("cardnumber"),
            card_holder_name=values.get("cardholdername"),
            card_expiration=card_expiration,
            card_security_number=values.get("cardsecuritynumber"),
            card_type_id=card_type_id,
            buyer=values.get("buyer"),
            request_id=request_id,
        )
