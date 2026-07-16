"""Redis data compatibility: Python reads/writes basket entries interchangeably
with the .NET implementation (same keys, same PascalCase Newtonsoft layout)."""

from decimal import Decimal

from basket_api.models import BasketItem, CustomerBasket

# Exactly what RedisBasketRepository (JsonConvert.SerializeObject) writes.
DOTNET_ENTRY = (
    '{"BuyerId":"alice@eshop","Items":[{"Id":"basket-item-1","ProductId":1,'
    '"ProductName":".NET Bot Black Hoodie","UnitPrice":19.50,"OldUnitPrice":18.00,'
    '"Quantity":2,"PictureUrl":"http://catalog/items/1/pic/"}]}'
)


async def test_python_reads_dotnet_written_entry(redis_client, repository):
    await redis_client.set("alice@eshop", DOTNET_ENTRY)
    basket = await repository.get_basket("alice@eshop")
    assert basket is not None
    assert basket.buyer_id == "alice@eshop"
    item = basket.items[0]
    assert (item.id, item.product_id, item.quantity) == ("basket-item-1", 1, 2)
    assert item.unit_price == Decimal("19.50")
    assert item.old_unit_price == Decimal("18.00")


async def test_python_write_is_byte_identical_to_dotnet_layout(redis_client, repository):
    await redis_client.set("alice@eshop", DOTNET_ENTRY)
    basket = await repository.get_basket("alice@eshop")
    await repository.update_basket(basket)
    stored = await redis_client.get("alice@eshop")
    assert stored.decode("utf-8") == DOTNET_ENTRY  # keys AND value layout unchanged


async def test_keys_are_raw_buyer_ids(redis_client, repository):
    basket = CustomerBasket(BuyerId="bob@eshop", Items=[BasketItem(Id="1", ProductId=2, Quantity=1)])
    await repository.update_basket(basket)
    assert await redis_client.get("bob@eshop") is not None
    users = [user async for user in repository.get_users()]
    assert users == ["bob@eshop"]


async def test_delete_returns_whether_key_existed(repository):
    basket = CustomerBasket(BuyerId="bob@eshop", Items=[])
    await repository.update_basket(basket)
    assert await repository.delete_basket("bob@eshop") is True
    assert await repository.delete_basket("bob@eshop") is False
