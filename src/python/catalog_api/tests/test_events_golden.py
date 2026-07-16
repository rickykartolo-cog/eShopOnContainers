"""Byte-for-byte serialization parity with the frozen event goldens, plus
routing-key naming and tolerant consumption of producer payloads."""

import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from catalog_api.events import (
    ConfirmedOrderStockItem,
    OrderStatusChangedToAwaitingValidationIntegrationEvent,
    OrderStatusChangedToPaidIntegrationEvent,
    OrderStockConfirmedIntegrationEvent,
    OrderStockRejectedIntegrationEvent,
    ProductPriceChangedIntegrationEvent,
)

GOLDEN_DIR = Path(__file__).resolve().parents[4] / "contracts" / "events"
PINNED_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
PINNED_DATE = datetime(2020, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)


def golden(name: str) -> str:
    return (GOLDEN_DIR / f"{name}.golden.json").read_text(encoding="utf-8").strip()


def test_product_price_changed_matches_golden():
    event = ProductPriceChangedIntegrationEvent(
        ProductId=1, NewPrice=Decimal("21.50"), OldPrice=Decimal("19.50"),
        Id=PINNED_ID, CreationDate=PINNED_DATE,
    )
    assert event.to_json() == golden("ProductPriceChangedIntegrationEvent")
    assert type(event).event_name() == "ProductPriceChangedIntegrationEvent"  # routing key


def test_order_stock_confirmed_matches_golden():
    event = OrderStockConfirmedIntegrationEvent(OrderId=42, Id=PINNED_ID, CreationDate=PINNED_DATE)
    assert event.to_json() == golden("OrderStockConfirmedIntegrationEvent")


def test_order_stock_rejected_matches_golden():
    event = OrderStockRejectedIntegrationEvent(
        OrderId=42,
        OrderStockItems=[
            ConfirmedOrderStockItem(ProductId=1, HasStock=False),
            ConfirmedOrderStockItem(ProductId=2, HasStock=True),
        ],
        Id=PINNED_ID,
        CreationDate=PINNED_DATE,
    )
    assert event.to_json() == golden("OrderStockRejectedIntegrationEvent")


def test_consumed_events_parse_dotnet_producer_payloads():
    awaiting = OrderStatusChangedToAwaitingValidationIntegrationEvent.from_json(
        golden("OrderStatusChangedToAwaitingValidationIntegrationEvent")
    )
    assert awaiting.order_id == 42
    assert [(i.product_id, i.units) for i in awaiting.order_stock_items] == [(1, 2), (3, 1)]
    assert awaiting.id == PINNED_ID

    paid = OrderStatusChangedToPaidIntegrationEvent.from_json(
        golden("OrderStatusChangedToPaidIntegrationEvent")
    )
    assert paid.order_id == 42
    assert [(i.product_id, i.units) for i in paid.order_stock_items] == [(1, 2), (3, 1)]


def test_service_bus_labels_drop_suffix():
    assert ProductPriceChangedIntegrationEvent.service_bus_label() == "ProductPriceChanged"
    assert OrderStockConfirmedIntegrationEvent.service_bus_label() == "OrderStockConfirmed"


def test_rejected_event_field_order_matches_newtonsoft():
    payload = json.loads(golden("OrderStockRejectedIntegrationEvent"))
    assert list(payload.keys()) == ["OrderId", "OrderStockItems", "Id", "CreationDate"]
