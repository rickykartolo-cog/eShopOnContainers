"""Byte-for-byte serialization parity with the frozen event goldens, plus
routing-key naming and tolerant consumption of producer payloads."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from payment_api.events import (
    OrderPaymentFailedIntegrationEvent,
    OrderPaymentSucceededIntegrationEvent,
    OrderStatusChangedToStockConfirmedIntegrationEvent,
)

GOLDEN_DIR = Path(__file__).resolve().parents[4] / "contracts" / "events"
PINNED_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
PINNED_DATE = datetime(2020, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)


def golden(name: str) -> str:
    return (GOLDEN_DIR / f"{name}.golden.json").read_text(encoding="utf-8").strip()


def test_order_payment_succeeded_matches_golden():
    event = OrderPaymentSucceededIntegrationEvent(OrderId=42, Id=PINNED_ID, CreationDate=PINNED_DATE)
    assert event.to_json() == golden("OrderPaymentSucceededIntegrationEvent")
    assert type(event).event_name() == "OrderPaymentSucceededIntegrationEvent"  # routing key


def test_order_payment_failed_matches_golden():
    event = OrderPaymentFailedIntegrationEvent(OrderId=42, Id=PINNED_ID, CreationDate=PINNED_DATE)
    assert event.to_json() == golden("OrderPaymentFailedIntegrationEvent")
    assert type(event).event_name() == "OrderPaymentFailedIntegrationEvent"


def test_consumed_event_parses_dotnet_producer_payload():
    event = OrderStatusChangedToStockConfirmedIntegrationEvent.from_json(
        golden("OrderStatusChangedToStockConfirmedIntegrationEvent")
    )
    assert event.order_id == 42
    assert event.id == PINNED_ID
    assert event.creation_date == PINNED_DATE


def test_service_bus_labels_drop_suffix():
    assert OrderPaymentSucceededIntegrationEvent.service_bus_label() == "OrderPaymentSucceeded"
    assert OrderPaymentFailedIntegrationEvent.service_bus_label() == "OrderPaymentFailed"
    assert (
        OrderStatusChangedToStockConfirmedIntegrationEvent.service_bus_label()
        == "OrderStatusChangedToStockConfirmed"
    )


def test_payment_event_field_order_matches_newtonsoft():
    payload = json.loads(golden("OrderPaymentSucceededIntegrationEvent"))
    assert list(payload.keys()) == ["OrderId", "Id", "CreationDate"]
