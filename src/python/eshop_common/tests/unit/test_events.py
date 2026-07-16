import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pydantic import Field

from eshop_common.events import (
    IntegrationEvent,
    newtonsoft_datetime,
    parse_newtonsoft_datetime,
)

GOLDEN = Path(__file__).parents[2] / "docs" / "golden" / "newtonsoft-product-price-changed.jsonl"


class ProductPriceChangedIntegrationEvent(IntegrationEvent):
    product_id: int = Field(alias="ProductId")
    new_price: Decimal = Field(alias="NewPrice")
    old_price: Decimal = Field(alias="OldPrice")


def test_matches_newtonsoft_golden_output_exactly():
    golden_lines = GOLDEN.read_text().strip().splitlines()
    event = ProductPriceChangedIntegrationEvent(
        ProductId=42,
        NewPrice=Decimal("12.50"),
        OldPrice=Decimal("10.0"),
        Id=uuid.UUID("a1a2a3a4-b1b2-c1c2-d1d2-e1e2e3e4e5e6"),
        CreationDate=datetime(2026, 7, 16, 2, 3, 4, 567890, tzinfo=UTC),
    )
    assert event.to_json() == golden_lines[0]

    event2 = ProductPriceChangedIntegrationEvent(
        ProductId=7,
        NewPrice=Decimal("100.0"),
        OldPrice=Decimal("99.99"),
        Id=uuid.UUID("a1a2a3a4-b1b2-c1c2-d1d2-e1e2e3e4e5e6"),
        CreationDate=datetime(2026, 7, 16, 2, 3, 4, tzinfo=UTC),
    )
    assert event2.to_json() == golden_lines[1]


def test_base_fields_serialized_last_with_pascal_case():
    event = ProductPriceChangedIntegrationEvent(
        ProductId=1, NewPrice=Decimal("1.5"), OldPrice=Decimal("2.5")
    )
    keys = list(json.loads(event.to_json()))
    assert keys == ["ProductId", "NewPrice", "OldPrice", "Id", "CreationDate"]


def test_round_trip_from_dotnet_payload():
    payload = GOLDEN.read_text().strip().splitlines()[0]
    event = ProductPriceChangedIntegrationEvent.from_json(payload)
    assert event.product_id == 42
    assert event.new_price == Decimal("12.50")
    assert event.creation_date == datetime(2026, 7, 16, 2, 3, 4, 567890, tzinfo=UTC)
    assert event.to_json() == payload


def test_default_id_and_creation_date():
    event = IntegrationEvent()
    assert isinstance(event.id, uuid.UUID)
    assert event.creation_date.tzinfo is not None
    assert event.creation_date.utcoffset().total_seconds() == 0


def test_event_name_and_service_bus_label():
    assert ProductPriceChangedIntegrationEvent.event_name() == "ProductPriceChangedIntegrationEvent"
    assert ProductPriceChangedIntegrationEvent.service_bus_label() == "ProductPriceChanged"


def test_datetime_formatting_edge_cases():
    assert newtonsoft_datetime(datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)) == "2026-01-02T03:04:05Z"
    assert newtonsoft_datetime(datetime(2026, 1, 2, 3, 4, 5, 100000, tzinfo=UTC)) == "2026-01-02T03:04:05.1Z"
    assert newtonsoft_datetime(datetime(2026, 1, 2, 3, 4, 5, 123456, tzinfo=UTC)) == "2026-01-02T03:04:05.123456Z"


def test_datetime_parsing_accepts_seven_fraction_digits():
    parsed = parse_newtonsoft_datetime("2026-07-16T02:03:04.5678901Z")
    assert parsed == datetime(2026, 7, 16, 2, 3, 4, 567890, tzinfo=UTC)
    assert parse_newtonsoft_datetime("2026-07-16T02:03:04Z") == datetime(2026, 7, 16, 2, 3, 4, tzinfo=UTC)


def test_guid_serialized_lowercase():
    event = IntegrationEvent(Id=uuid.UUID("A1A2A3A4-B1B2-C1C2-D1D2-E1E2E3E4E5E6"))
    assert '"a1a2a3a4-b1b2-c1c2-d1d2-e1e2e3e4e5e6"' in event.to_json()
