"""Mixed-stack producer/consumer tests on real RabbitMQ (§6.3.5/6.3.7).

- .NET producer → Python consumer: publish the exact golden Newtonsoft bytes for
  ``OrderStatusChangedToStockConfirmedIntegrationEvent`` the way Ordering does
  (direct exchange ``eshop_event_bus``, routing key = class name, persistent).
- Python producer → .NET consumer: consume the resulting payment event with a
  raw AMQP client bound the way Ordering's queue is, asserting routing key,
  exchange, persistence, and exact wire fields.
- Duplicate delivery over the broker produces exactly one payment event.
"""

import asyncio
import json
import uuid

import aio_pika
import pytest
from eshop_common.eventbus.rabbitmq import BROKER_NAME, RabbitMQEventBus
from eshop_common.testing import rabbitmq_host
from payment_test_helpers import make_settings

from payment_api.consumers import PaymentEventConsumers

pytestmark = pytest.mark.integration

GOLDEN_STOCK_CONFIRMED = (
    b'{"OrderId":42,"OrderStatus":"stockconfirmed","BuyerName":"alice@eshop",'
    b'"Id":"11111111-2222-3333-4444-555555555555",'
    b'"CreationDate":"2020-01-02T03:04:05.678Z"}'
)


async def _ordering_style_queue(routing_key: str):
    """Bind a queue exactly like a .NET consumer (Ordering) would."""
    connection = await aio_pika.connect(host=rabbitmq_host())
    channel = await connection.channel()
    exchange = await channel.declare_exchange(BROKER_NAME, aio_pika.ExchangeType.DIRECT, durable=False)
    queue = await channel.declare_queue(f"ordering-test-{uuid.uuid4()}", durable=True)
    await queue.bind(exchange, routing_key=routing_key)
    return connection, exchange, queue


async def _start_payment_consumer(payment_succeeded: str) -> RabbitMQEventBus:
    settings = make_settings(
        PaymentSucceeded=payment_succeeded,
        EventBusConnection=rabbitmq_host(),
        SubscriptionClientName=f"Payment-test-{uuid.uuid4()}",
    )
    bus = RabbitMQEventBus(
        host=settings.event_bus_connection,
        queue_name=settings.subscription_client_name,
    )
    consumers = PaymentEventConsumers(settings, bus)
    await consumers.subscribe_all()
    await bus.start_consuming()
    return bus


async def test_dotnet_producer_python_consumer_publishes_succeeded():
    connection, exchange, queue = await _ordering_style_queue("OrderPaymentSucceededIntegrationEvent")
    bus = await _start_payment_consumer("True")
    try:
        await exchange.publish(
            aio_pika.Message(body=GOLDEN_STOCK_CONFIRMED, delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
            routing_key="OrderStatusChangedToStockConfirmedIntegrationEvent",
        )
        message = await queue.get(timeout=15, fail=True)
        assert message.routing_key == "OrderPaymentSucceededIntegrationEvent"
        assert message.exchange == BROKER_NAME
        assert message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
        payload = json.loads(message.body)
        assert list(payload.keys()) == ["OrderId", "Id", "CreationDate"]
        assert payload["OrderId"] == 42
        uuid.UUID(payload["Id"])  # lowercase GUID text
        assert payload["Id"] == payload["Id"].lower()
        assert payload["CreationDate"].endswith("Z")
        await message.ack()
    finally:
        await bus.close()
        await queue.delete()
        await connection.close()


async def test_payment_failed_toggle_publishes_failed():
    connection, exchange, queue = await _ordering_style_queue("OrderPaymentFailedIntegrationEvent")
    bus = await _start_payment_consumer("False")
    try:
        await exchange.publish(
            aio_pika.Message(body=GOLDEN_STOCK_CONFIRMED, delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
            routing_key="OrderStatusChangedToStockConfirmedIntegrationEvent",
        )
        message = await queue.get(timeout=15, fail=True)
        assert message.routing_key == "OrderPaymentFailedIntegrationEvent"
        payload = json.loads(message.body)
        assert payload["OrderId"] == 42
        await message.ack()
    finally:
        await bus.close()
        await queue.delete()
        await connection.close()


async def test_duplicate_delivery_over_broker_publishes_once():
    connection, exchange, queue = await _ordering_style_queue("OrderPaymentSucceededIntegrationEvent")
    bus = await _start_payment_consumer("True")
    try:
        for _ in range(2):
            await exchange.publish(
                aio_pika.Message(
                    body=GOLDEN_STOCK_CONFIRMED, delivery_mode=aio_pika.DeliveryMode.PERSISTENT
                ),
                routing_key="OrderStatusChangedToStockConfirmedIntegrationEvent",
            )
        first = await queue.get(timeout=15, fail=True)
        await first.ack()
        await asyncio.sleep(2)
        with pytest.raises(aio_pika.exceptions.QueueEmpty):
            await queue.get(timeout=1, fail=True)
    finally:
        await bus.close()
        await queue.delete()
        await connection.close()
