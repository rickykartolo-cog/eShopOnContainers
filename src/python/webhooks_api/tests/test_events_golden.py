"""Golden parity for the three consumed integration events: the .NET-serialized
golden bytes must deserialize into the consumer classes, routing keys must equal
the class names (exchange ``eshop_event_bus``), and re-serializing the consumer
copy must match the frozen bytes for the fields it declares."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from pathlib import Path

from webhooks_api.events import (
    OrderStatusChangedToPaidIntegrationEvent,
    OrderStatusChangedToShippedIntegrationEvent,
    ProductPriceChangedIntegrationEvent,
)

GOLDEN_DIR = Path(__file__).resolve().parents[4] / "contracts" / "events"

EVENT_TYPES = {
    "ProductPriceChangedIntegrationEvent": ProductPriceChangedIntegrationEvent,
    "OrderStatusChangedToShippedIntegrationEvent": OrderStatusChangedToShippedIntegrationEvent,
    "OrderStatusChangedToPaidIntegrationEvent": OrderStatusChangedToPaidIntegrationEvent,
}


def test_routing_keys_equal_class_names():
    for name, event_type in EVENT_TYPES.items():
        assert event_type.event_name() == name
        assert event_type.service_bus_label() == name.replace("IntegrationEvent", "")


def test_product_price_changed_golden_roundtrip():
    golden = (GOLDEN_DIR / "ProductPriceChangedIntegrationEvent.golden.json").read_text()
    event = ProductPriceChangedIntegrationEvent.from_json(golden)
    assert event.product_id == 1
    assert event.new_price == Decimal("21.50")
    assert event.old_price == Decimal("19.50")
    assert event.id == uuid.UUID("11111111-2222-3333-4444-555555555555")
    assert event.to_json() == golden


def test_order_shipped_golden_roundtrip():
    golden = (GOLDEN_DIR / "OrderStatusChangedToShippedIntegrationEvent.golden.json").read_text()
    event = OrderStatusChangedToShippedIntegrationEvent.from_json(golden)
    assert event.order_id == 42
    assert event.order_status == "shipped"
    assert event.buyer_name == "alice@eshop"
    assert event.to_json() == golden


def test_order_paid_consumer_copy_ignores_extra_producer_fields():
    golden = (GOLDEN_DIR / "OrderStatusChangedToPaidIntegrationEvent.golden.json").read_text()
    event = OrderStatusChangedToPaidIntegrationEvent.from_json(golden)
    assert event.order_id == 42
    assert [(item.product_id, item.units) for item in event.order_stock_items] == [(1, 2), (3, 1)]
    # The Webhooks copy declares OrderId + OrderStockItems only; the producer's
    # OrderStatus/BuyerName are dropped, matching Newtonsoft deserialization
    # into the .NET consumer class.
    reserialized = json.loads(event.to_json())
    golden_data = json.loads(golden)
    assert set(reserialized) == {"OrderId", "OrderStockItems", "Id", "CreationDate"}
    for key in reserialized:
        assert reserialized[key] == golden_data[key]


def test_goldens_match_schemas():
    for name in EVENT_TYPES:
        golden = json.loads((GOLDEN_DIR / f"{name}.golden.json").read_text())
        schema = json.loads((GOLDEN_DIR / f"{name}.schema.json").read_text())
        assert set(golden) == set(schema["properties"])
