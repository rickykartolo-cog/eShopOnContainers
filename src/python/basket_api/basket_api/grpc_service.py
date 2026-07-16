"""gRPC Basket service, port of ``BasketService`` (Grpc/BasketService.cs)
against the unchanged ``basket.proto``:

- ``GetBasketById``: missing basket → NOT_FOUND (empty response message).
- ``UpdateBasket``: stores the mapped basket and returns it field-for-field;
  a failed store → NOT_FOUND, matching the .NET null-response branch.
"""

from __future__ import annotations

from decimal import Decimal

import grpc

from basket_api.grpc_gen import basket_pb2, basket_pb2_grpc
from basket_api.models import BasketItem, CustomerBasket
from basket_api.repository import RedisBasketRepository


def _map_to_response(basket: CustomerBasket) -> basket_pb2.CustomerBasketResponse:
    response = basket_pb2.CustomerBasketResponse(buyerid=basket.buyer_id or "")
    for item in basket.items:
        response.items.add(
            id=item.id or "",
            productid=item.product_id,
            productname=item.product_name or "",
            unitprice=float(item.unit_price),
            oldunitprice=float(item.old_unit_price),
            quantity=item.quantity,
            pictureurl=item.picture_url or "",
        )
    return response


def _map_to_basket(request: basket_pb2.CustomerBasketRequest) -> CustomerBasket:
    return CustomerBasket(
        BuyerId=request.buyerid,
        Items=[
            BasketItem(
                Id=item.id,
                ProductId=item.productid,
                ProductName=item.productname,
                UnitPrice=Decimal(repr(item.unitprice)),
                OldUnitPrice=Decimal(repr(item.oldunitprice)),
                Quantity=item.quantity,
                PictureUrl=item.pictureurl,
            )
            for item in request.items
        ],
    )


class BasketGrpcService(basket_pb2_grpc.BasketServicer):
    def __init__(self, repository: RedisBasketRepository) -> None:
        self._repository = repository

    async def GetBasketById(self, request, context):  # noqa: N802 (proto naming)
        data = await self._repository.get_basket(request.id)
        if data is not None:
            return _map_to_response(data)
        context.set_code(grpc.StatusCode.NOT_FOUND)
        context.set_details(f"Basket with id {request.id} do not exist")
        return basket_pb2.CustomerBasketResponse()

    async def UpdateBasket(self, request, context):  # noqa: N802 (proto naming)
        customer_basket = _map_to_basket(request)
        response = await self._repository.update_basket(customer_basket)
        if response is not None:
            return _map_to_response(response)
        context.set_code(grpc.StatusCode.NOT_FOUND)
        context.set_details(f"Basket with buyer id {request.buyerid} do not exist")
        return basket_pb2.CustomerBasketResponse()


def create_grpc_server(repository: RedisBasketRepository) -> grpc.aio.Server:
    server = grpc.aio.server()
    basket_pb2_grpc.add_BasketServicer_to_server(BasketGrpcService(repository), server)
    return server
