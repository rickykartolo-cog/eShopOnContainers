"""Commands (CQRS write side), ports of ``Ordering.API/Application/Commands``.

Pydantic models bind the same camelCase JSON the .NET model binder accepted, and
the validators mirror the FluentValidation rules (``CreateOrderCommandValidator``,
``CancelOrderCommandValidator``, ``ShipOrderCommandValidator``,
``IdentifiedCommandValidator``). Validation failures raise
``CommandValidationError`` which the pipeline maps to the same 400 response the
.NET ``ValidatorBehavior`` + ``HttpGlobalExceptionFilter`` produced.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from ordering_api.events import BasketItemData


class CommandValidationError(Exception):
    """Raised when a command fails its (ported FluentValidation) rules."""

    def __init__(self, command_type: str, failures: list[str]) -> None:
        super().__init__(f"Command Validation Errors for type {command_type}")
        self.failures = failures


class Command(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    def validate_command(self) -> list[str]:
        """Return validation failure messages (empty when valid)."""
        return []


class OrderItemDTO(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    product_id: int = Field(default=0, alias="productId")
    product_name: str | None = Field(default=None, alias="productName")
    unit_price: Decimal = Field(default=Decimal(0), alias="unitPrice")
    discount: Decimal = Field(default=Decimal(0), alias="discount")
    units: int = Field(default=0, alias="units")
    picture_url: str | None = Field(default=None, alias="pictureUrl")


class CreateOrderCommand(Command):
    user_id: str | None = Field(default=None, alias="userId")
    user_name: str | None = Field(default=None, alias="userName")
    city: str | None = Field(default=None, alias="city")
    street: str | None = Field(default=None, alias="street")
    state: str | None = Field(default=None, alias="state")
    country: str | None = Field(default=None, alias="country")
    zip_code: str | None = Field(default=None, alias="zipCode")
    card_number: str | None = Field(default=None, alias="cardNumber")
    card_holder_name: str | None = Field(default=None, alias="cardHolderName")
    card_expiration: datetime = Field(default=datetime.min, alias="cardExpiration")
    card_security_number: str | None = Field(default=None, alias="cardSecurityNumber")
    card_type_id: int = Field(default=0, alias="cardTypeId")
    order_items: list[OrderItemDTO] = Field(default_factory=list, alias="orderItems")

    def validate_command(self) -> list[str]:
        failures: list[str] = []
        if not self.city:
            failures.append("No city found")
        if not self.street:
            failures.append("No street found")
        if not self.state:
            failures.append("No state found")
        if not self.country:
            failures.append("No country found")
        if not self.zip_code:
            failures.append("No zip code found")
        if not self.card_number or not (12 <= len(self.card_number) <= 19):
            failures.append("Please specify a valid card number")
        if not self.card_holder_name:
            failures.append("No card holder name found")
        if _expired(self.card_expiration):
            failures.append("Please specify a valid card expiration date")
        if not self.card_security_number or len(self.card_security_number) != 3:
            failures.append("Please specify a valid card security number")
        if self.card_type_id == 0:
            failures.append("card type id required")
        if not self.order_items:
            failures.append("No order items found")
        return failures


class CancelOrderCommand(Command):
    order_number: int = Field(default=0, alias="orderNumber")

    def validate_command(self) -> list[str]:
        return ["No orderId found"] if not self.order_number else []


class ShipOrderCommand(Command):
    order_number: int = Field(default=0, alias="orderNumber")

    def validate_command(self) -> list[str]:
        return ["No orderId found"] if not self.order_number else []


class CreateOrderDraftCommand(Command):
    buyer_id: str | None = Field(default=None, alias="buyerId")
    items: list[BasketItemData] = Field(default_factory=list, alias="items")


class SetAwaitingValidationOrderStatusCommand(Command):
    order_number: int = Field(alias="orderNumber")


class SetStockConfirmedOrderStatusCommand(Command):
    order_number: int = Field(alias="orderNumber")


class SetStockRejectedOrderStatusCommand(Command):
    order_number: int = Field(alias="orderNumber")
    order_stock_items: list[int] = Field(alias="orderStockItems")


class SetPaidOrderStatusCommand(Command):
    order_number: int = Field(alias="orderNumber")


class IdentifiedCommand[TCommand: Command](BaseModel):
    """Port of ``IdentifiedCommand<T, R>`` carrying the x-requestid GUID."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    command: TCommand
    id: uuid.UUID

    def validate_command(self) -> list[str]:
        return []


def _expired(expiration: datetime) -> bool:
    now = datetime.now(UTC).replace(tzinfo=None)
    value = expiration
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value < now
