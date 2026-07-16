"""Mixed-stack wire contract on a real RabbitMQ broker: the Python producer
publishes ``UserLocationUpdatedIntegrationEvent`` to the same exchange and
routing key the .NET Marketing consumer binds to, with the frozen JSON body."""

from __future__ import annotations

import asyncio
import json
import uuid

import aio_pika
import pytest
from eshop_common.eventbus.rabbitmq import BROKER_NAME, RabbitMQEventBus
from eshop_common.testing import rabbitmq_host

from locations_api.events import UserLocationDetails, UserLocationUpdatedIntegrationEvent

pytestmark = pytest.mark.integration

ROUTING_KEY = "UserLocationUpdatedIntegrationEvent"


async def test_marketing_style_consumer_receives_python_published_event():
    """Bind a queue exactly like the .NET Marketing subscription manager does
    (direct exchange ``eshop_event_bus``, routing key = event class name) and
    assert the delivered payload parses as the frozen contract."""
    queue_name = f"marketing-wire-test-{uuid.uuid4()}"
    connection = await aio_pika.connect(host=rabbitmq_host())
    channel = await connection.channel()
    exchange = await channel.declare_exchange(BROKER_NAME, aio_pika.ExchangeType.DIRECT, durable=False)
    queue = await channel.declare_queue(queue_name, durable=True)
    await queue.bind(exchange, routing_key=ROUTING_KEY)

    bus = RabbitMQEventBus(host=rabbitmq_host(), queue_name=f"locations-pub-{uuid.uuid4()}")
    event = UserLocationUpdatedIntegrationEvent(
        UserId="4611ce3f-380d-4db5-8d76-87a8689058ed",
        LocationList=[UserLocationDetails(LocationId=4, Code="SEAT", Description="Seattle")],
    )
    await bus.publish(event)

    message = await asyncio.wait_for(queue.get(timeout=10), timeout=15)
    await message.ack()

    assert message.routing_key == ROUTING_KEY
    assert message.delivery_mode == aio_pika.DeliveryMode.PERSISTENT

    payload = json.loads(message.body.decode("utf-8"))
    assert list(payload.keys()) == ["UserId", "LocationList", "Id", "CreationDate"]
    assert payload["UserId"] == "4611ce3f-380d-4db5-8d76-87a8689058ed"
    assert payload["LocationList"] == [{"LocationId": 4, "Code": "SEAT", "Description": "Seattle"}]

    await bus.close()
    await queue.delete()
    await connection.close()


async def test_duplicate_delivery_is_tolerated_by_consumer_parsing():
    """The contract payload parses identically on redelivery (consumers are
    idempotent per master prompt §6.3; Locations only produces this event)."""
    body = UserLocationUpdatedIntegrationEvent(
        UserId="u", LocationList=[UserLocationDetails(LocationId=1)]
    ).to_json()
    first = UserLocationUpdatedIntegrationEvent.from_json(body)
    second = UserLocationUpdatedIntegrationEvent.from_json(body)
    assert first.id == second.id
    assert first.location_list[0].location_id == second.location_list[0].location_id
