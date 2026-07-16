from __future__ import annotations

import abc
from collections.abc import Awaitable, Callable

from eshop_common.events import IntegrationEvent

EventHandler = Callable[[IntegrationEvent], Awaitable[None]]


class SubscriptionRegistry:
    """Maps event names to (event type, handlers), mirroring the .NET subscriptions manager."""

    def __init__(self) -> None:
        self._event_types: dict[str, type[IntegrationEvent]] = {}
        self._handlers: dict[str, list[EventHandler]] = {}

    def add(self, event_type: type[IntegrationEvent], handler: EventHandler) -> None:
        name = event_type.event_name()
        self._event_types[name] = event_type
        self._handlers.setdefault(name, []).append(handler)

    def remove(self, event_type: type[IntegrationEvent], handler: EventHandler) -> None:
        name = event_type.event_name()
        handlers = self._handlers.get(name, [])
        if handler in handlers:
            handlers.remove(handler)
        if not handlers:
            self._handlers.pop(name, None)
            self._event_types.pop(name, None)

    def event_type(self, event_name: str) -> type[IntegrationEvent] | None:
        return self._event_types.get(event_name)

    def handlers(self, event_name: str) -> list[EventHandler]:
        return list(self._handlers.get(event_name, ()))

    def event_names(self) -> list[str]:
        return list(self._handlers)


class EventBus(abc.ABC):
    """Publish/subscribe contract shared by both broker adapters."""

    @abc.abstractmethod
    async def publish(self, event: IntegrationEvent) -> None: ...

    @abc.abstractmethod
    async def subscribe(self, event_type: type[IntegrationEvent], handler: EventHandler) -> None: ...

    @abc.abstractmethod
    async def unsubscribe(self, event_type: type[IntegrationEvent], handler: EventHandler) -> None: ...

    @abc.abstractmethod
    async def start_consuming(self) -> None: ...

    @abc.abstractmethod
    async def close(self) -> None: ...
