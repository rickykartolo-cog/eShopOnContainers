"""Azure Service Bus adapter preserving the .NET EventBusServiceBus contract.

- topic messages with Label/Subject = event class name without the trailing
  ``IntegrationEvent`` suffix
- per-event subscription correlation-filter rules named after that label
- the ``IntegrationEvent`` suffix is re-appended when resolving the event type
  on receipt
"""

from __future__ import annotations

import asyncio
import uuid

import structlog
from azure.servicebus import ServiceBusMessage
from azure.servicebus.aio import ServiceBusClient
from azure.servicebus.aio.management import ServiceBusAdministrationClient
from azure.servicebus.management import CorrelationRuleFilter

from eshop_common.eventbus.base import EventBus, EventHandler, SubscriptionRegistry
from eshop_common.events import IntegrationEvent

TOPIC_NAME = "eshop_event_bus"
INTEGRATION_EVENT_SUFFIX = IntegrationEvent.INTEGRATION_EVENT_SUFFIX

logger = structlog.get_logger(__name__)


class AzureServiceBusEventBus(EventBus):
    def __init__(
        self,
        connection_string: str,
        subscription_name: str,
        topic_name: str = TOPIC_NAME,
    ) -> None:
        self._connection_string = connection_string
        self._subscription_name = subscription_name
        self._topic_name = topic_name
        self._registry = SubscriptionRegistry()
        self._client: ServiceBusClient | None = None
        self._receiver_task = None

    def _get_client(self) -> ServiceBusClient:
        if self._client is None:
            self._client = ServiceBusClient.from_connection_string(self._connection_string)
        return self._client

    async def publish(self, event: IntegrationEvent) -> None:
        label = type(event).service_bus_label()
        message = ServiceBusMessage(
            body=event.to_json().encode("utf-8"),
            message_id=str(uuid.uuid4()),
            subject=label,
        )
        async with self._get_client().get_topic_sender(self._topic_name) as sender:
            await sender.send_messages(message)
        logger.debug("published_event", event_id=str(event.id), label=label)

    async def subscribe(self, event_type: type[IntegrationEvent], handler: EventHandler) -> None:
        label = event_type.service_bus_label()
        already_subscribed = bool(self._registry.handlers(event_type.event_name()))
        self._registry.add(event_type, handler)
        if not already_subscribed:
            async with ServiceBusAdministrationClient.from_connection_string(
                self._connection_string
            ) as admin:
                try:
                    await admin.create_rule(
                        self._topic_name,
                        self._subscription_name,
                        rule_name=label,
                        filter=CorrelationRuleFilter(label=label),
                    )
                except Exception:
                    logger.warning("subscription_rule_exists", label=label)

    async def unsubscribe(self, event_type: type[IntegrationEvent], handler: EventHandler) -> None:
        label = event_type.service_bus_label()
        self._registry.remove(event_type, handler)
        if not self._registry.handlers(event_type.event_name()):
            async with ServiceBusAdministrationClient.from_connection_string(
                self._connection_string
            ) as admin:
                try:
                    await admin.delete_rule(self._topic_name, self._subscription_name, label)
                except Exception:
                    logger.warning("subscription_rule_missing", label=label)

    async def start_consuming(self) -> None:
        async def _consume() -> None:
            receiver = self._get_client().get_subscription_receiver(
                self._topic_name, self._subscription_name
            )
            async with receiver:
                async for message in receiver:
                    label = message.subject or ""
                    event_name = f"{label}{INTEGRATION_EVENT_SUFFIX}"
                    try:
                        body = b"".join(
                            part if isinstance(part, bytes) else bytes(part)
                            for part in message.body
                        )
                        await self._process_event(event_name, body)
                        await receiver.complete_message(message)
                    except Exception:
                        logger.warning("error_processing_message", event_name=event_name, exc_info=True)
                        await receiver.abandon_message(message)

        self._receiver_task = asyncio.create_task(_consume())

    async def _process_event(self, event_name: str, body: bytes) -> None:
        event_type = self._registry.event_type(event_name)
        if event_type is None:
            logger.warning("no_subscription_for_event", event_name=event_name)
            return
        event = event_type.from_json(body)
        for handler in self._registry.handlers(event_name):
            await handler(event)

    async def close(self) -> None:
        if self._receiver_task is not None:
            self._receiver_task.cancel()
            self._receiver_task = None
        if self._client is not None:
            await self._client.close()
            self._client = None
