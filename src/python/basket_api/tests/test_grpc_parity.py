"""Field-by-field gRPC parity with the .NET BasketService against the
unchanged basket.proto: GetBasketById and UpdateBasket, including NotFound."""

import grpc
import pytest

from basket_api.grpc_gen import basket_pb2
from basket_api.grpc_service import BasketGrpcService


class FakeContext:
    def __init__(self) -> None:
        self.code = None
        self.details = None

    def set_code(self, code) -> None:
        self.code = code

    def set_details(self, details) -> None:
        self.details = details


@pytest.fixture
def service(repository) -> BasketGrpcService:
    return BasketGrpcService(repository)


def _customer_basket_request() -> basket_pb2.CustomerBasketRequest:
    request = basket_pb2.CustomerBasketRequest(buyerid="alice@eshop")
    request.items.add(
        id="basket-item-1",
        productid=1,
        productname=".NET Bot Black Hoodie",
        unitprice=19.5,
        oldunitprice=18.0,
        quantity=2,
        pictureurl="http://catalog/items/1/pic/",
    )
    return request


async def test_get_basket_by_id_missing_returns_not_found(service):
    context = FakeContext()
    response = await service.GetBasketById(basket_pb2.BasketRequest(id="nobody"), context)
    assert context.code == grpc.StatusCode.NOT_FOUND
    assert response == basket_pb2.CustomerBasketResponse()


async def test_update_then_get_field_for_field(service):
    context = FakeContext()
    updated = await service.UpdateBasket(_customer_basket_request(), context)
    assert context.code is None
    assert updated.buyerid == "alice@eshop"
    assert len(updated.items) == 1
    item = updated.items[0]
    assert item.id == "basket-item-1"
    assert item.productid == 1
    assert item.productname == ".NET Bot Black Hoodie"
    assert item.unitprice == 19.5
    assert item.oldunitprice == 18.0
    assert item.quantity == 2
    assert item.pictureurl == "http://catalog/items/1/pic/"

    fetched = await service.GetBasketById(basket_pb2.BasketRequest(id="alice@eshop"), FakeContext())
    assert fetched == updated


async def test_update_empty_items_roundtrip(service):
    context = FakeContext()
    updated = await service.UpdateBasket(basket_pb2.CustomerBasketRequest(buyerid="bob@eshop"), context)
    assert context.code is None
    assert updated.buyerid == "bob@eshop"
    assert len(updated.items) == 0
