"""Mixed-stack event tests against a real RabbitMQ broker (rabbitmq:3-management-alpine)
and real Redis (redis:alpine), matching the existing test topology.

- .NET producer (golden Newtonsoft bytes on exchange ``eshop_event_bus``) →
  Python consumer side effects on Redis.
- Python producer → persistent message with the exact routing key and
  Newtonsoft byte layout a .NET consumer deserializes.

Run with the test dependencies up:
    docker run -d -p 5672:5672 rabbitmq:3-management-alpine
    docker run -d -p 6379:6379 redis:alpine
    pytest -m integration src/python/basket_api/tests/test_mixed_stack_rabbitmq.py
"""

import asyncio
import json
import uuid
from datetime import UTC, datetime

import aio_pika
import pytest
import redis.asyncio as aioredis
from eshop_common.eventbus.rabbitmq import BROKER_NAME, RabbitMQEventBus
from eshop_common.testing import rabbitmq_host, redis_url

from basket_api.consumers import BasketEventConsumers
from basket_api.events import UserCheckoutAcceptedIntegrationEvent
from basket_api.models import BasketItem, CustomerBasket
from basket_api.repository import RedisBasketRepository

pytestmark = pytest.mark.integration

DOTNET_ENTRY = (
    '{"BuyerId":"alice@eshop","Items":[{"Id":"basket-item-1","ProductId":1,'
    '"ProductName":".NET Bot Black Hoodie","UnitPrice":19.50,"OldUnitPrice":0.0,'
    '"Quantity":2,"PictureUrl":"http://catalog/items/1/pic/"}]}'
)


@pytest.fixture
async def live_redis():
    client = aioredis.from_url(redis_url())
    await client.flushdb()
    yield client
    await client.aclose()


@pytest.fixture
async def basket_bus():
    bus = RabbitMQEventBus(host=rabbitmq_host(), queue_name=f"Basket-test-{uuid.uuid4().hex[:8]}")
    yield bus
    await bus.close()


async def _publish_raw(routing_key: str, body: bytes) -> None:
    connection = await aio_pika.connect_robust(host=rabbitmq_host())
    async with connection:
        channel = await connection.channel()
        exchange = await channel.declare_exchange(BROKER_NAME, aio_pika.ExchangeType.DIRECT, durable=False)
        await exchange.publish(
            aio_pika.Message(body=body, delivery_mode=aio_pika.DeliveryMode.PERSISTENT),
            routing_key=routing_key,
        )


async def test_dotnet_producer_python_consumer_price_change(live_redis, basket_bus):
    repository = RedisBasketRepository(live_redis)
    await live_redis.set("alice@eshop", DOTNET_ENTRY)

    consumers = BasketEventConsumers(repository, basket_bus)
    await consumers.subscribe_all()
    await basket_bus.start_consuming()

    body = (
        '{"ProductId":1,"NewPrice":21.50,"OldPrice":19.50,'
        f'"Id":"{uuid.uuid4()}","CreationDate":"2020-01-02T03:04:05.678Z"}}'
    ).encode()
    await _publish_raw("ProductPriceChangedIntegrationEvent", body)

    for _ in range(50):
        basket = await repository.get_basket("alice@eshop")
        if basket and str(basket.items[0].unit_price) == "21.50":
            break
        await asyncio.sleep(0.2)
    basket = await repository.get_basket("alice@eshop")
    assert str(basket.items[0].unit_price) == "21.50"
    assert str(basket.items[0].old_unit_price) == "19.50"


async def test_python_producer_emits_dotnet_compatible_checkout(basket_bus):
    connection = await aio_pika.connect_robust(host=rabbitmq_host())
    async with connection:
        channel = await connection.channel()
        await channel.declare_exchange(BROKER_NAME, aio_pika.ExchangeType.DIRECT, durable=False)
        queue = await channel.declare_queue(f"dotnet-ordering-sim-{uuid.uuid4().hex[:8]}", durable=True)
        await queue.bind(BROKER_NAME, routing_key="UserCheckoutAcceptedIntegrationEvent")

        event = UserCheckoutAcceptedIntegrationEvent(
            UserId="e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5",
            UserName="alice@eshop",
            City="Seattle",
            Street="123 Main St",
            State="WA",
            Country="U.S.",
            ZipCode="98101",
            CardNumber="4012888888881881",
            CardHolderName="Alice Smith",
            CardExpiration=datetime(2025, 12, 31, tzinfo=UTC),
            CardSecurityNumber="535",
            CardTypeId=1,
            Buyer="alice@eshop",
            RequestId=uuid.uuid4(),
            Basket=CustomerBasket(
                BuyerId="alice@eshop",
                Items=[BasketItem(Id="1", ProductId=1, ProductName="x", Quantity=2)],
            ),
        )
        await basket_bus.publish(event)

        message = await queue.get(timeout=10)
        assert message.routing_key == "UserCheckoutAcceptedIntegrationEvent"
        assert message.delivery_mode == 2  # persistent, like the .NET publisher
        payload = json.loads(message.body)
        # Newtonsoft-compatible layout a .NET consumer binds field-for-field.
        assert payload["UserId"] == "e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5"
        assert payload["Basket"]["BuyerId"] == "alice@eshop"
        assert payload["Basket"]["Items"][0]["ProductId"] == 1
        assert payload["CardExpiration"] == "2025-12-31T00:00:00Z"
        assert list(payload)[-2:] == ["Id", "CreationDate"]
        await message.ack()
