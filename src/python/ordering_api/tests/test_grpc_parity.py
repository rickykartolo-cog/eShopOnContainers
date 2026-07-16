"""gRPC parity against the unchanged ordering.proto: status codes, detail
strings, and field-for-field responses (Grpc/OrderingService.cs oracle)."""

import grpc

from ordering_api.grpc_gen import ordering_pb2
from ordering_api.grpc_service import OrderingGrpcService


class FakeContext:
    def __init__(self) -> None:
        self.code = grpc.StatusCode.OK
        self.details = ""

    def set_code(self, code) -> None:
        self.code = code

    def set_details(self, details) -> None:
        self.details = details


def draft_request() -> ordering_pb2.CreateOrderDraftCommand:
    return ordering_pb2.CreateOrderDraftCommand(
        buyerId="e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5",
        items=[
            ordering_pb2.BasketItem(
                id="basket-item-1",
                productId=1,
                productName=".NET Bot Black Hoodie",
                unitPrice=19.5,
                oldUnitPrice=18.0,
                quantity=2,
                pictureUrl="http://pic/1",
            ),
            ordering_pb2.BasketItem(
                id="basket-item-2",
                productId=1,
                productName=".NET Bot Black Hoodie",
                unitPrice=19.5,
                oldUnitPrice=18.0,
                quantity=1,
                pictureUrl="http://pic/1",
            ),
        ],
    )


async def test_create_order_draft_field_parity(session_factory, event_bus, mediator):
    service = OrderingGrpcService(session_factory, mediator, event_bus)
    context = FakeContext()
    response = await service.CreateOrderDraftFromBasketData(draft_request(), context)

    assert context.code == grpc.StatusCode.OK
    assert context.details.startswith(" ordering get order draft ")
    assert context.details.endswith(" do exist")

    assert response.total == 58.5
    assert len(response.orderItems) == 1  # duplicate products merged
    item = response.orderItems[0]
    assert item.productId == 1
    assert item.productName == ".NET Bot Black Hoodie"
    assert item.unitPrice == 19.5
    assert item.discount == 0.0
    assert item.units == 3
    assert item.pictureUrl == "http://pic/1"


async def test_empty_basket_draft_returns_ok_with_zero_total(session_factory, event_bus, mediator):
    service = OrderingGrpcService(session_factory, mediator, event_bus)
    context = FakeContext()
    request = ordering_pb2.CreateOrderDraftCommand(buyerId="buyer", items=[])
    response = await service.CreateOrderDraftFromBasketData(request, context)
    # The .NET handler always returns a DTO (never null), so the status is OK.
    assert context.code == grpc.StatusCode.OK
    assert response.total == 0.0
    assert len(response.orderItems) == 0
