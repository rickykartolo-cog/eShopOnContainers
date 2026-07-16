"""subscribe_all must survive a broker that is not yet accepting connections
without registering duplicate handlers."""

import pytest
from eshop_common.eventbus.base import EventBus, SubscriptionRegistry

from ordering_signalrhub.events import (
    ORDER_STATUS_EVENTS,
    OrderStatusChangedToShippedIntegrationEvent,
)
from ordering_signalrhub.handlers import subscribe_all
from ordering_signalrhub.hub import NotificationHub


class FlakyBus(EventBus):
    def __init__(self, failures: int) -> None:
        self._failures = failures
        self.registry = SubscriptionRegistry()
        self.consuming = False

    async def publish(self, event) -> None:
        raise NotImplementedError

    async def subscribe(self, event_type, handler) -> None:
        self.registry.add(event_type, handler)

    async def unsubscribe(self, event_type, handler) -> None:
        self.registry.remove(event_type, handler)

    async def start_consuming(self) -> None:
        if self._failures > 0:
            self._failures -= 1
            raise ConnectionError("broker not ready")
        self.consuming = True

    async def close(self) -> None:
        pass


@pytest.fixture
def hub(idp):
    from eshop_common.auth import OidcJwtValidator

    return NotificationHub(OidcJwtValidator(authority=idp, audience="orders.signalrhub"))


async def test_retries_until_broker_ready_without_duplicate_handlers(hub, monkeypatch):
    bus = FlakyBus(failures=2)
    await subscribe_all(bus, hub, timeout_seconds=30, retry_delay_seconds=0.01)

    assert bus.consuming
    for event_type in ORDER_STATUS_EVENTS:
        assert len(bus.registry.handlers(event_type.event_name())) == 1

    emitted = []

    async def fake_emit(event, data=None, room=None, **kwargs):
        emitted.append((event, data, room))

    monkeypatch.setattr(hub.sio, "emit", fake_emit)
    event = OrderStatusChangedToShippedIntegrationEvent(
        OrderId=42, OrderStatus="shipped", BuyerName="alice@eshop"
    )
    for handler in bus.registry.handlers(event.event_name()):
        await handler(event)
    assert len(emitted) == 1


async def test_raises_after_deadline(hub):
    bus = FlakyBus(failures=1000)
    with pytest.raises(ConnectionError):
        await subscribe_all(bus, hub, timeout_seconds=0.05, retry_delay_seconds=0.01)
