"""Unit tests for the Order aggregate, state machine, validators, and HiLo
generator (oracles: Ordering.UnitTests + Ordering.Domain)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from ordering_api.commands import CancelOrderCommand, CreateOrderCommand, OrderItemDTO
from ordering_api.models import (
    Address,
    Order,
    OrderingDomainException,
    OrderStatus,
)

ADDRESS = Address("street", "city", "state", "country", "zipcode")
FUTURE = datetime.now(UTC) + timedelta(days=365)


def new_order() -> Order:
    return Order.create("userId", "userName", ADDRESS, 1, "12345678901234", "123", "name", FUTURE)


def test_create_order_raises_started_domain_event():
    order = new_order()
    assert [type(e).__name__ for e in order.domain_events] == ["OrderStartedDomainEvent"]
    assert order.OrderStatusId == OrderStatus.Submitted[0]
    assert order.status_name == "submitted"


def test_add_order_item_merges_duplicates_and_keeps_highest_discount():
    order = new_order()
    order.add_order_item(1, "cup", Decimal("10.00"), Decimal("1.00"), None, 1)
    order.add_order_item(1, "cup", Decimal("10.00"), Decimal("2.00"), None, 2)
    assert len(order.order_items) == 1
    item = order.order_items[0]
    assert item.get_units() == 3
    assert item.get_current_discount() == Decimal("2.00")


def test_invalid_units_rejected():
    order = new_order()
    with pytest.raises(OrderingDomainException):
        order.add_order_item(1, "cup", Decimal("10.00"), Decimal(0), None, 0)


def test_total_is_units_times_price_ignoring_discount():
    # GetTotal() in .NET sums units * unit price without applying discounts.
    order = new_order()
    order.add_order_item(1, "cup", Decimal("10.00"), Decimal("1.00"), None, 2)
    assert order.get_total() == Decimal("20.00")


def test_state_machine_happy_path():
    order = new_order()
    order.set_awaiting_validation_status()
    assert order.status_name == "awaitingvalidation"
    order.set_stock_confirmed_status()
    assert order.status_name == "stockconfirmed"
    order.set_paid_status()
    assert order.status_name == "paid"
    order.set_shipped_status()
    assert order.status_name == "shipped"


def test_cannot_ship_unpaid_order():
    order = new_order()
    with pytest.raises(OrderingDomainException):
        order.set_shipped_status()


def test_cannot_cancel_shipped_order():
    order = new_order()
    order.set_awaiting_validation_status()
    order.set_stock_confirmed_status()
    order.set_paid_status()
    order.set_shipped_status()
    with pytest.raises(OrderingDomainException):
        order.set_cancelled_status()


def test_stock_rejected_builds_description_from_rejected_items():
    order = new_order()
    order.add_order_item(1, "cup", Decimal("10.00"), Decimal(0), None, 1)
    order.add_order_item(2, "plate", Decimal("5.00"), Decimal(0), None, 1)
    order.set_awaiting_validation_status()
    order.set_cancelled_status_when_stock_is_rejected([1])
    assert order.status_name == "cancelled"
    assert order.Description == "The product items don't have stock: (cup)."


def test_create_order_command_validation_messages():
    command = CreateOrderCommand(
        userId="u",
        userName="n",
        city="",
        street="street",
        state="state",
        country="country",
        zipCode="zip",
        cardNumber="123",  # too short
        cardHolderName="",
        cardExpiration=datetime(2000, 1, 1, tzinfo=UTC),  # expired
        cardSecurityNumber="12345",
        cardTypeId=1,
        orderItems=[],
    )
    failures = command.validate_command()
    assert "No city found" in failures
    assert "Please specify a valid card number" in failures
    assert "No card holder name found" in failures
    assert "Please specify a valid card expiration date" in failures
    assert "Please specify a valid card security number" in failures
    assert "No order items found" in failures


def test_cancel_order_command_requires_order_number():
    assert CancelOrderCommand(orderNumber=0).validate_command() == ["No orderId found"]
    assert CancelOrderCommand(orderNumber=7).validate_command() == []


def test_order_item_dto_binding():
    dto = OrderItemDTO(productId=1, productName="cup", unitPrice=Decimal("10.0"), units=2)
    assert dto.discount == 0
