"""gRPC Ordering service against the unchanged ``ordering.proto``: port of
``OrderingService.CreateOrderDraftFromBasketData`` (Grpc/OrderingService.cs),
field-for-field including the OK/NOT_FOUND status details."""

from __future__ import annotations

from decimal import Decimal

import grpc
import structlog
from google.protobuf import json_format
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ordering_api.commands import CreateOrderDraftCommand
from ordering_api.events import BasketItemData
from ordering_api.grpc_gen import ordering_pb2, ordering_pb2_grpc
from ordering_api.integration import execute_command_transaction
from ordering_api.mediator import Mediator

logger = structlog.get_logger(__name__)


class OrderingGrpcService(ordering_pb2_grpc.OrderingGrpcServicer):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        mediator: Mediator,
        event_bus,
    ) -> None:
        self._session_factory = session_factory
        self._mediator = mediator
        self._event_bus = event_bus

    async def CreateOrderDraftFromBasketData(self, request, context):  # noqa: N802 (proto naming)
        command = CreateOrderDraftCommand(
            buyerId=request.buyerId,
            items=[
                BasketItemData(
                    Id=item.id,
                    ProductId=item.productId,
                    ProductName=item.productName,
                    UnitPrice=Decimal(str(item.unitPrice)),
                    OldUnitPrice=Decimal(str(item.oldUnitPrice)),
                    Quantity=item.quantity,
                    PictureUrl=item.pictureUrl,
                )
                for item in request.items
            ],
        )
        async with self._session_factory() as session:
            data = await execute_command_transaction(session, self._mediator, self._event_bus, command)

        request_text = json_format.MessageToJson(request, indent=None)
        if data is not None:
            context.set_code(grpc.StatusCode.OK)
            context.set_details(f" ordering get order draft {request_text} do exist")
            return _map_response(data)
        context.set_code(grpc.StatusCode.NOT_FOUND)
        context.set_details(f" ordering get order draft {request_text} do not exist")
        return ordering_pb2.OrderDraftDTO()


def _map_response(draft: dict) -> ordering_pb2.OrderDraftDTO:
    result = ordering_pb2.OrderDraftDTO(total=float(draft["total"]))
    for item in draft["orderItems"]:
        result.orderItems.add(
            discount=float(item["discount"]),
            pictureUrl=item["pictureUrl"] or "",
            productId=item["productId"],
            productName=item["productName"] or "",
            unitPrice=float(item["unitPrice"]),
            units=item["units"],
        )
    return result


def create_grpc_server(
    session_factory: async_sessionmaker[AsyncSession], mediator: Mediator, event_bus
) -> grpc.aio.Server:
    server = grpc.aio.server()
    ordering_pb2_grpc.add_OrderingGrpcServicer_to_server(
        OrderingGrpcService(session_factory, mediator, event_bus), server
    )
    return server
