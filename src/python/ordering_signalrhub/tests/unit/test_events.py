"""Golden JSON parity for the six consumed order-status events."""

import pytest

from ordering_signalrhub.events import ORDER_STATUS_EVENTS

from ..conftest import contracts_events_dir


@pytest.mark.parametrize("event_type", ORDER_STATUS_EVENTS, ids=lambda t: t.__name__)
def test_parses_golden_json(event_type):
    golden = (contracts_events_dir() / f"{event_type.event_name()}.golden.json").read_text()
    event = event_type.from_json(golden)
    assert event.order_id == 42
    assert event.buyer_name == "alice@eshop"
    assert str(event.id) == "11111111-2222-3333-4444-555555555555"


@pytest.mark.parametrize("event_type", ORDER_STATUS_EVENTS, ids=lambda t: t.__name__)
def test_round_trips_to_exact_golden_bytes(event_type):
    """Field names, casing, and order must match the Newtonsoft.Json golden exactly."""
    golden = (contracts_events_dir() / f"{event_type.event_name()}.golden.json").read_text().strip()
    assert event_type.from_json(golden).to_json() == golden


@pytest.mark.parametrize("event_type", ORDER_STATUS_EVENTS, ids=lambda t: t.__name__)
def test_routing_key_is_class_name(event_type):
    assert event_type.event_name() == event_type.__name__
    assert event_type.event_name().endswith("IntegrationEvent")
