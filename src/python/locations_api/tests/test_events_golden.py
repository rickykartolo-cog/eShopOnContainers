"""Byte-for-byte serialization parity with the frozen
``UserLocationUpdatedIntegrationEvent`` golden (consumed by Marketing), plus
routing-key naming and consumption of .NET producer payloads."""

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from locations_api.events import UserLocationDetails, UserLocationUpdatedIntegrationEvent

GOLDEN_DIR = Path(__file__).resolve().parents[4] / "contracts" / "events"
PINNED_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
PINNED_DATE = datetime(2020, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)


def golden() -> str:
    return (GOLDEN_DIR / "UserLocationUpdatedIntegrationEvent.golden.json").read_text(encoding="utf-8").strip()


def make_event() -> UserLocationUpdatedIntegrationEvent:
    return UserLocationUpdatedIntegrationEvent(
        UserId="e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5",
        LocationList=[UserLocationDetails(LocationId=1, Code="SEAT", Description="Seattle")],
        Id=PINNED_ID,
        CreationDate=PINNED_DATE,
    )


def test_user_location_updated_matches_golden():
    assert make_event().to_json() == golden()


def test_routing_key_is_full_event_class_name():
    assert UserLocationUpdatedIntegrationEvent.event_name() == "UserLocationUpdatedIntegrationEvent"


def test_service_bus_label_drops_suffix():
    assert UserLocationUpdatedIntegrationEvent.service_bus_label() == "UserLocationUpdated"


def test_field_order_matches_newtonsoft():
    payload = json.loads(make_event().to_json())
    assert list(payload.keys()) == ["UserId", "LocationList", "Id", "CreationDate"]
    assert list(payload["LocationList"][0].keys()) == ["LocationId", "Code", "Description"]


def test_consumes_dotnet_producer_payload():
    event = UserLocationUpdatedIntegrationEvent.from_json(golden())
    assert event.user_id == "e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5"
    assert [(d.location_id, d.code, d.description) for d in event.location_list] == [(1, "SEAT", "Seattle")]
    assert event.id == PINNED_ID
