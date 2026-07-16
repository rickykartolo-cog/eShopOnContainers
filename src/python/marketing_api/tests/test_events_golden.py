"""Byte-for-byte serialization parity with the frozen
``UserLocationUpdatedIntegrationEvent`` golden, routing-key naming, and tolerant
consumption of .NET (Location service) producer payloads."""

import uuid
from datetime import UTC, datetime
from pathlib import Path

from marketing_api.events import UserLocationDetails, UserLocationUpdatedIntegrationEvent

GOLDEN_DIR = Path(__file__).resolve().parents[4] / "contracts" / "events"
PINNED_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")
PINNED_DATE = datetime(2020, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)


def golden(name: str) -> str:
    return (GOLDEN_DIR / f"{name}.golden.json").read_text(encoding="utf-8").strip()


def test_user_location_updated_matches_golden():
    event = UserLocationUpdatedIntegrationEvent(
        UserId="e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5",
        LocationList=[UserLocationDetails(LocationId=1, Code="SEAT", Description="Seattle")],
        Id=PINNED_ID,
        CreationDate=PINNED_DATE,
    )
    assert event.to_json() == golden("UserLocationUpdatedIntegrationEvent")
    assert type(event).event_name() == "UserLocationUpdatedIntegrationEvent"  # routing key


def test_consumed_event_parses_dotnet_producer_payload():
    event = UserLocationUpdatedIntegrationEvent.from_json(golden("UserLocationUpdatedIntegrationEvent"))
    assert event.user_id == "e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5"
    assert [(loc.location_id, loc.code, loc.description) for loc in event.location_list] == [
        (1, "SEAT", "Seattle")
    ]
    assert event.id == PINNED_ID
    assert event.creation_date == PINNED_DATE
