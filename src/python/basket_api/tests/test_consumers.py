"""Consumer side effects and duplicate-delivery safety, using the application
IntegrationEventsScenarios (Catalog price change → Basket price update) as the
oracle."""

import json
import uuid
from decimal import Decimal

import pytest

from basket_api.consumers import BasketEventConsumers
from basket_api.events import OrderStartedIntegrationEvent, ProductPriceChangedIntegrationEvent

DOTNET_ENTRY = (
    '{"BuyerId":"alice@eshop","Items":[{"Id":"basket-item-1","ProductId":1,'
    '"ProductName":".NET Bot Black Hoodie","UnitPrice":19.50,"OldUnitPrice":0.0,'
    '"Quantity":2,"PictureUrl":"http://catalog/items/1/pic/"}]}'
)


@pytest.fixture
async def consumers(repository, event_bus):
    consumers = BasketEventConsumers(repository, event_bus)
    await consumers.subscribe_all()
    return consumers


def _price_changed_body(new_price: str, old_price: str) -> bytes:
    return (
        f'{{"ProductId":1,"NewPrice":{new_price},"OldPrice":{old_price},'
        f'"Id":"{uuid.uuid4()}","CreationDate":"2020-01-02T03:04:05.678Z"}}'
    ).encode()


async def test_product_price_changed_updates_current_and_old_prices(
    redis_client, repository, event_bus, consumers
):
    await redis_client.set("alice@eshop", DOTNET_ENTRY)
    await event_bus.deliver("ProductPriceChangedIntegrationEvent", _price_changed_body("21.50", "19.50"))

    basket = await repository.get_basket("alice@eshop")
    assert basket.items[0].unit_price == Decimal("21.50")
    assert basket.items[0].old_unit_price == Decimal("19.50")


async def test_duplicate_price_changed_delivery_has_no_additional_side_effects(
    redis_client, repository, event_bus, consumers
):
    await redis_client.set("alice@eshop", DOTNET_ENTRY)
    body = _price_changed_body("21.50", "19.50")
    await event_bus.deliver("ProductPriceChangedIntegrationEvent", body)
    first = await redis_client.get("alice@eshop")
    await event_bus.deliver("ProductPriceChangedIntegrationEvent", body)
    assert await redis_client.get("alice@eshop") == first
    basket = await repository.get_basket("alice@eshop")
    assert basket.items[0].unit_price == Decimal("21.50")
    assert basket.items[0].old_unit_price == Decimal("19.50")


async def test_price_changed_skips_items_at_other_prices(redis_client, repository, event_bus, consumers):
    await redis_client.set("alice@eshop", DOTNET_ENTRY)
    await event_bus.deliver("ProductPriceChangedIntegrationEvent", _price_changed_body("25.00", "10.00"))
    basket = await repository.get_basket("alice@eshop")
    assert basket.items[0].unit_price == Decimal("19.50")
    assert basket.items[0].old_unit_price == Decimal("0.0")


async def test_order_started_deletes_buyer_basket(redis_client, event_bus, consumers):
    await redis_client.set("alice@eshop", DOTNET_ENTRY)
    event = OrderStartedIntegrationEvent(UserId="alice@eshop")
    await event_bus.deliver("OrderStartedIntegrationEvent", event.to_json().encode())
    assert await redis_client.get("alice@eshop") is None
    # duplicate delivery: deleting an absent basket is a no-op
    await event_bus.deliver("OrderStartedIntegrationEvent", event.to_json().encode())
    assert await redis_client.get("alice@eshop") is None


async def test_consumed_event_types_tolerate_extra_producer_fields():
    payload = json.dumps(
        {
            "ProductId": 1,
            "NewPrice": 21.5,
            "OldPrice": 19.5,
            "Extra": "ignored",
            "Id": str(uuid.uuid4()),
            "CreationDate": "2020-01-02T03:04:05.678Z",
        }
    )
    event = ProductPriceChangedIntegrationEvent.from_json(payload)
    assert event.product_id == 1
