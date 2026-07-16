"""In-memory event bus and settings builders shared across the Payment tests."""

from __future__ import annotations

from eshop_common.config import Settings
from eshop_common.eventbus.base import EventBus, SubscriptionRegistry

from payment_api.settings import PaymentSettings


class InMemoryEventBus(EventBus):
    def __init__(self) -> None:
        self.published = []
        self.fail_publish = False
        self._registry = SubscriptionRegistry()

    async def publish(self, event) -> None:
        if self.fail_publish:
            raise ConnectionError("broker unavailable")
        self.published.append(event)

    async def subscribe(self, event_type, handler) -> None:
        self._registry.add(event_type, handler)

    async def unsubscribe(self, event_type, handler) -> None:
        self._registry.remove(event_type, handler)

    async def start_consuming(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def deliver(self, event) -> None:
        for handler in self._registry.handlers(type(event).event_name()):
            await handler(event)


BASE_ENV = {
    "EventBusConnection": "rabbitmq",
    "SubscriptionClientName": "Payment",
    "AzureServiceBusEnabled": "False",
    "EventBusRetryCount": "5",
}


def make_settings(**overrides: str) -> PaymentSettings:
    return PaymentSettings(Settings({**BASE_ENV, **overrides}))
