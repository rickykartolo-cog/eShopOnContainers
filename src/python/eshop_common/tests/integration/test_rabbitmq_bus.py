"""RabbitMQ adapter wire-contract tests against rabbitmq:3-management-alpine."""

import asyncio
import json
import uuid

import aio_pika
import pytest
from pydantic import Field

from eshop_common.eventbus.rabbitmq import BROKER_NAME, RabbitMQEventBus
from eshop_common.events import IntegrationEvent
from eshop_common.testing import rabbitmq_host

pytestmark = pytest.mark.integration


class ProductPriceChangedIntegrationEvent(IntegrationEvent):
    ProductId: int
    NewPrice: float
    OldPrice: float


class OrderStartedIntegrationEvent(IntegrationEvent):
    UserId: str = Field(default="")


async def test_publish_uses_direct_exchange_routing_key_and_persistent_message():
    """Consume with a raw AMQP client the way a .NET service would."""
    queue_name = f"wire-test-{uuid.uuid4()}"
    connection = await aio_pika.connect(host=rabbitmq_host())
    channel = await connection.channel()
    exchange = await channel.declare_exchange(BROKER_NAME, aio_pika.ExchangeType.DIRECT, durable=False)
    queue = await channel.declare_queue(queue_name, durable=True)
    await queue.bind(exchange, routing_key="ProductPriceChangedIntegrationEvent")

    bus = RabbitMQEventBus(host=rabbitmq_host(), queue_name=f"pub-{uuid.uuid4()}")
    event = ProductPriceChangedIntegrationEvent(ProductId=1, NewPrice=12.5, OldPrice=10.0)
    await bus.publish(event)

    message = await queue.get(timeout=10)
    assert message.routing_key == "ProductPriceChangedIntegrationEvent"
    assert message.exchange == BROKER_NAME
    assert message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT
    payload = json.loads(message.body)
    assert payload["ProductId"] == 1
    assert payload["Id"] == str(event.id)
    assert payload["CreationDate"].endswith("Z")
    await message.ack()
    await queue.delete()
    await connection.close()
    await bus.close()


async def test_subscribe_and_receive_round_trip():
    received: list[IntegrationEvent] = []
    done = asyncio.Event()

    async def handler(event: IntegrationEvent) -> None:
        received.append(event)
        done.set()

    queue_name = f"roundtrip-{uuid.uuid4()}"
    consumer = RabbitMQEventBus(host=rabbitmq_host(), queue_name=queue_name)
    await consumer.subscribe(OrderStartedIntegrationEvent, handler)
    await consumer.start_consuming()

    publisher = RabbitMQEventBus(host=rabbitmq_host(), queue_name=f"pub-{uuid.uuid4()}")
    sent = OrderStartedIntegrationEvent(UserId="alice")
    await publisher.publish(sent)

    await asyncio.wait_for(done.wait(), timeout=15)
    assert len(received) == 1
    assert isinstance(received[0], OrderStartedIntegrationEvent)
    assert received[0].UserId == "alice"
    assert received[0].id == sent.id
    assert received[0].creation_date == sent.creation_date
    await publisher.close()
    await consumer.close()


async def test_handler_failure_still_acks_matching_reference_behavior():
    """The .NET bus logs and acks on handler failure; the queue must not grow."""
    attempts = 0
    done = asyncio.Event()

    async def failing_handler(_event: IntegrationEvent) -> None:
        nonlocal attempts
        attempts += 1
        done.set()
        raise RuntimeError("handler blew up")

    queue_name = f"failure-{uuid.uuid4()}"
    consumer = RabbitMQEventBus(host=rabbitmq_host(), queue_name=queue_name)
    await consumer.subscribe(OrderStartedIntegrationEvent, failing_handler)
    await consumer.start_consuming()

    publisher = RabbitMQEventBus(host=rabbitmq_host(), queue_name=f"pub-{uuid.uuid4()}")
    await publisher.publish(OrderStartedIntegrationEvent(UserId="bob"))
    await asyncio.wait_for(done.wait(), timeout=15)
    await asyncio.sleep(1)
    assert attempts == 1  # message acked, not redelivered
    await publisher.close()
    await consumer.close()


async def test_deserialization_of_dotnet_style_payload():
    """Publish raw bytes exactly as Newtonsoft would produce them."""
    received: list[OrderStartedIntegrationEvent] = []
    done = asyncio.Event()

    async def handler(event: IntegrationEvent) -> None:
        received.append(event)
        done.set()

    queue_name = f"dotnet-payload-{uuid.uuid4()}"
    consumer = RabbitMQEventBus(host=rabbitmq_host(), queue_name=queue_name)
    await consumer.subscribe(OrderStartedIntegrationEvent, handler)
    await consumer.start_consuming()

    connection = await aio_pika.connect(host=rabbitmq_host())
    channel = await connection.channel()
    exchange = await channel.get_exchange(BROKER_NAME)
    body = (
        b'{"UserId":"carol","Id":"a1a2a3a4-b1b2-c1c2-d1d2-e1e2e3e4e5e6",'
        b'"CreationDate":"2026-07-16T02:03:04.5678901Z"}'
    )
    await exchange.publish(
        aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
        routing_key="OrderStartedIntegrationEvent",
    )
    await asyncio.wait_for(done.wait(), timeout=15)
    assert received[0].UserId == "carol"
    assert str(received[0].id) == "a1a2a3a4-b1b2-c1c2-d1d2-e1e2e3e4e5e6"
    await connection.close()
    await consumer.close()
