"""Byte-for-byte serialization parity with the frozen event goldens, routing-key
naming, and tolerant consumption of .NET producer payloads."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ordering_api.events import (
    GracePeriodConfirmedIntegrationEvent,
    OrderPaymentFailedIntegrationEvent,
    OrderPaymentSucceededIntegrationEvent,
    OrderStartedIntegrationEvent,
    OrderStatusChangedToAwaitingValidationIntegrationEvent,
    OrderStatusChangedToCancelledIntegrationEvent,
    OrderStatusChangedToPaidIntegrationEvent,
    OrderStatusChangedToShippedIntegrationEvent,
    OrderStatusChangedToStockConfirmedIntegrationEvent,
    OrderStatusChangedToSubmittedIntegrationEvent,
    OrderStockConfirmedIntegrationEvent,
    OrderStockItem,
    OrderStockRejectedIntegrationEvent,
    UserCheckoutAcceptedIntegrationEvent,
)

GOLDEN_DIR = Path(__file__).resolve().parents[4] / "contracts" / "events"
PINNED_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
PINNED_DATE = datetime(2020, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)
PINNED = {"Id": PINNED_ID, "CreationDate": PINNED_DATE}


def golden(name: str) -> str:
    return (GOLDEN_DIR / f"{name}.golden.json").read_text(encoding="utf-8").strip()


def test_order_started_matches_golden():
    event = OrderStartedIntegrationEvent(UserId="e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5", **PINNED)
    assert event.to_json() == golden("OrderStartedIntegrationEvent")
    assert type(event).event_name() == "OrderStartedIntegrationEvent"  # routing key


def test_status_changed_to_submitted_matches_golden():
    event = OrderStatusChangedToSubmittedIntegrationEvent(
        OrderId=42, OrderStatus="submitted", BuyerName="alice@eshop", **PINNED
    )
    assert event.to_json() == golden("OrderStatusChangedToSubmittedIntegrationEvent")


def test_status_changed_to_awaiting_validation_matches_golden():
    event = OrderStatusChangedToAwaitingValidationIntegrationEvent(
        OrderId=42,
        OrderStatus="awaitingvalidation",
        BuyerName="alice@eshop",
        OrderStockItems=[OrderStockItem(ProductId=1, Units=2), OrderStockItem(ProductId=3, Units=1)],
        **PINNED,
    )
    assert event.to_json() == golden("OrderStatusChangedToAwaitingValidationIntegrationEvent")


def test_status_changed_to_stock_confirmed_matches_golden():
    event = OrderStatusChangedToStockConfirmedIntegrationEvent(
        OrderId=42, OrderStatus="stockconfirmed", BuyerName="alice@eshop", **PINNED
    )
    assert event.to_json() == golden("OrderStatusChangedToStockConfirmedIntegrationEvent")


def test_status_changed_to_paid_matches_golden():
    event = OrderStatusChangedToPaidIntegrationEvent(
        OrderId=42,
        OrderStatus="paid",
        BuyerName="alice@eshop",
        OrderStockItems=[OrderStockItem(ProductId=1, Units=2), OrderStockItem(ProductId=3, Units=1)],
        **PINNED,
    )
    assert event.to_json() == golden("OrderStatusChangedToPaidIntegrationEvent")


def test_status_changed_to_shipped_matches_golden():
    event = OrderStatusChangedToShippedIntegrationEvent(
        OrderId=42, OrderStatus="shipped", BuyerName="alice@eshop", **PINNED
    )
    assert event.to_json() == golden("OrderStatusChangedToShippedIntegrationEvent")


def test_status_changed_to_cancelled_matches_golden():
    event = OrderStatusChangedToCancelledIntegrationEvent(
        OrderId=42, OrderStatus="cancelled", BuyerName="alice@eshop", **PINNED
    )
    assert event.to_json() == golden("OrderStatusChangedToCancelledIntegrationEvent")


def test_consumed_events_parse_dotnet_producer_payloads():
    checkout = UserCheckoutAcceptedIntegrationEvent.from_json(golden("UserCheckoutAcceptedIntegrationEvent"))
    assert checkout.user_id == "e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5"
    assert checkout.request_id == uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    assert checkout.card_type_id == 1
    assert [(i.product_id, i.quantity, i.unit_price) for i in checkout.basket.items] == [
        (1, 2, Decimal("19.50"))
    ]

    grace = GracePeriodConfirmedIntegrationEvent.from_json(golden("GracePeriodConfirmedIntegrationEvent"))
    assert grace.order_id == 42

    confirmed = OrderStockConfirmedIntegrationEvent.from_json(golden("OrderStockConfirmedIntegrationEvent"))
    assert confirmed.order_id == 42

    rejected = OrderStockRejectedIntegrationEvent.from_json(golden("OrderStockRejectedIntegrationEvent"))
    assert rejected.order_id == 42
    assert [(i.product_id, i.has_stock) for i in rejected.order_stock_items] == [(1, False), (2, True)]

    paid = OrderPaymentSucceededIntegrationEvent.from_json(golden("OrderPaymentSucceededIntegrationEvent"))
    assert paid.order_id == 42

    failed = OrderPaymentFailedIntegrationEvent.from_json(golden("OrderPaymentFailedIntegrationEvent"))
    assert failed.order_id == 42


def test_routing_keys_and_service_bus_labels():
    assert OrderStartedIntegrationEvent.event_name() == "OrderStartedIntegrationEvent"
    assert OrderStartedIntegrationEvent.service_bus_label() == "OrderStarted"
    assert (
        OrderStatusChangedToAwaitingValidationIntegrationEvent.event_name()
        == "OrderStatusChangedToAwaitingValidationIntegrationEvent"
    )
    assert (
        OrderStatusChangedToCancelledIntegrationEvent.service_bus_label()
        == "OrderStatusChangedToCancelled"
    )
