"""Typed event-bus interface with RabbitMQ and Azure Service Bus adapters."""

from eshop_common.eventbus.base import EventBus, EventHandler, SubscriptionRegistry
from eshop_common.eventbus.rabbitmq import RabbitMQEventBus
from eshop_common.eventbus.servicebus import AzureServiceBusEventBus

__all__ = [
    "AzureServiceBusEventBus",
    "EventBus",
    "EventHandler",
    "RabbitMQEventBus",
    "SubscriptionRegistry",
]
