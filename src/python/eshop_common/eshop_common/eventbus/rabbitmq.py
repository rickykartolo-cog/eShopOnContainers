"""RabbitMQ adapter preserving the .NET EventBusRabbitMQ wire contract.

- direct exchange ``eshop_event_bus``
- routing key = integration-event class name
- persistent (delivery mode 2) UTF-8 JSON messages serialized like Newtonsoft.Json
- durable, non-exclusive queue named after the subscribing service
- consumer acks after handling; handler failures are logged, message still acked
  (matching the reference implementation's at-least-once + warn behavior)
"""

from __future__ import annotations

import asyncio

import aio_pika
import structlog
from aio_pika.abc import (
    AbstractIncomingMessage,
    AbstractRobustChannel,
    AbstractRobustConnection,
)
from tenacity import retry, stop_after_attempt, wait_exponential

from eshop_common.eventbus.base import EventBus, EventHandler, SubscriptionRegistry
from eshop_common.events import IntegrationEvent

BROKER_NAME = "eshop_event_bus"

logger = structlog.get_logger(__name__)


class RabbitMQEventBus(EventBus):
    def __init__(
        self,
        host: str,
        queue_name: str,
        username: str | None = None,
        password: str | None = None,
        retry_count: int = 5,
        port: int = 5672,
    ) -> None:
        self._host = host
        self._port = port
        self._queue_name = queue_name
        self._username = username or "guest"
        self._password = password or "guest"
        self._retry_count = retry_count
        self._registry = SubscriptionRegistry()
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractRobustChannel | None = None
        self._queue: aio_pika.abc.AbstractRobustQueue | None = None
        self._consumer_tag: str | None = None
        self._lock = asyncio.Lock()

    async def _ensure_connected(self) -> AbstractRobustChannel:
        async with self._lock:
            if self._connection is None or self._connection.is_closed:
                self._connection = await aio_pika.connect_robust(
                    host=self._host,
                    port=self._port,
                    login=self._username,
                    password=self._password,
                )
                self._channel = None
            if self._channel is None or self._channel.is_closed:
                self._channel = await self._connection.channel()
                await self._channel.declare_exchange(
                    BROKER_NAME, aio_pika.ExchangeType.DIRECT, durable=False
                )
                self._queue = await self._channel.declare_queue(
                    self._queue_name, durable=True, exclusive=False, auto_delete=False
                )
            return self._channel

    async def publish(self, event: IntegrationEvent) -> None:
        event_name = type(event).event_name()
        body = event.to_json().encode("utf-8")

        @retry(
            reraise=True,
            stop=stop_after_attempt(self._retry_count),
            wait=wait_exponential(multiplier=1, min=1, max=30),
        )
        async def _publish() -> None:
            channel = await self._ensure_connected()
            exchange = await channel.get_exchange(BROKER_NAME)
            await exchange.publish(
                aio_pika.Message(
                    body=body,
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                ),
                routing_key=event_name,
                mandatory=True,
            )

        logger.debug("publishing_event", event_id=str(event.id), event_name=event_name)
        await _publish()

    async def subscribe(self, event_type: type[IntegrationEvent], handler: EventHandler) -> None:
        already_bound = bool(self._registry.handlers(event_type.event_name()))
        self._registry.add(event_type, handler)
        if not already_bound:
            await self._ensure_connected()
            assert self._queue is not None
            await self._queue.bind(BROKER_NAME, routing_key=event_type.event_name())

    async def unsubscribe(self, event_type: type[IntegrationEvent], handler: EventHandler) -> None:
        self._registry.remove(event_type, handler)
        if not self._registry.handlers(event_type.event_name()) and self._queue is not None:
            await self._queue.unbind(BROKER_NAME, routing_key=event_type.event_name())

    async def start_consuming(self) -> None:
        await self._ensure_connected()
        assert self._queue is not None
        if self._consumer_tag is None:
            self._consumer_tag = await self._queue.consume(self._on_message, no_ack=False)

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        event_name = message.routing_key or ""
        try:
            await self._process_event(event_name, message.body)
        except Exception:
            logger.warning("error_processing_message", event_name=event_name, exc_info=True)
        # Match the reference implementation: ack even on handler failure.
        await message.ack()

    async def _process_event(self, event_name: str, body: bytes) -> None:
        event_type = self._registry.event_type(event_name)
        if event_type is None:
            logger.warning("no_subscription_for_event", event_name=event_name)
            return
        event = event_type.from_json(body)
        for handler in self._registry.handlers(event_name):
            await handler(event)

    async def close(self) -> None:
        if self._queue is not None and self._consumer_tag is not None:
            await self._queue.cancel(self._consumer_tag)
            self._consumer_tag = None
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = None
        self._channel = None
        self._queue = None
