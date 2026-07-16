"""Integration-event consumers, ports of the .NET Ordering.API handlers.

Duplicate delivery matches the .NET behavior: ``UserCheckoutAccepted`` is
idempotent through ``IdentifiedCommand`` + the ``ordering.requests`` table, and
the status-transition commands are naturally idempotent because the order state
machine only moves from the expected previous status.
"""

from __future__ import annotations

import uuid

import structlog
from eshop_common.eventbus.base import EventBus
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ordering_api.commands import (
    CancelOrderCommand,
    CreateOrderCommand,
    IdentifiedCommand,
    OrderItemDTO,
    SetAwaitingValidationOrderStatusCommand,
    SetPaidOrderStatusCommand,
    SetStockConfirmedOrderStatusCommand,
    SetStockRejectedOrderStatusCommand,
)
from ordering_api.events import (
    GracePeriodConfirmedIntegrationEvent,
    OrderPaymentFailedIntegrationEvent,
    OrderPaymentSucceededIntegrationEvent,
    OrderStockConfirmedIntegrationEvent,
    OrderStockRejectedIntegrationEvent,
    UserCheckoutAcceptedIntegrationEvent,
)
from ordering_api.integration import execute_command_transaction
from ordering_api.mediator import Mediator, SupportsValidation

logger = structlog.get_logger(__name__)


class OrderingEventConsumers:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        event_bus: EventBus,
        mediator: Mediator,
    ) -> None:
        self._session_factory = session_factory
        self._event_bus = event_bus
        self._mediator = mediator

    async def subscribe_all(self) -> None:
        await self._event_bus.subscribe(UserCheckoutAcceptedIntegrationEvent, self.on_user_checkout_accepted)
        await self._event_bus.subscribe(GracePeriodConfirmedIntegrationEvent, self.on_grace_period_confirmed)
        await self._event_bus.subscribe(OrderStockConfirmedIntegrationEvent, self.on_order_stock_confirmed)
        await self._event_bus.subscribe(OrderStockRejectedIntegrationEvent, self.on_order_stock_rejected)
        await self._event_bus.subscribe(OrderPaymentSucceededIntegrationEvent, self.on_order_payment_succeeded)
        await self._event_bus.subscribe(OrderPaymentFailedIntegrationEvent, self.on_order_payment_failed)

    async def _send(self, command: SupportsValidation) -> object:
        async with self._session_factory() as session:
            return await execute_command_transaction(session, self._mediator, self._event_bus, command)

    async def on_user_checkout_accepted(self, event) -> None:
        """Port of ``UserCheckoutAcceptedIntegrationEventHandler``: only a valid
        RequestId creates an (idempotent) order."""
        assert isinstance(event, UserCheckoutAcceptedIntegrationEvent)
        if event.request_id == uuid.UUID(int=0):
            logger.warning("invalid_integration_event", event_id=str(event.id))
            return
        command = CreateOrderCommand(
            userId=event.user_id,
            userName=event.user_name,
            city=event.city,
            street=event.street,
            state=event.state,
            country=event.country,
            zipCode=event.zip_code,
            cardNumber=event.card_number,
            cardHolderName=event.card_holder_name,
            cardExpiration=event.card_expiration,
            cardSecurityNumber=event.card_security_number,
            cardTypeId=event.card_type_id,
            orderItems=[
                OrderItemDTO(
                    productId=item.product_id,
                    productName=item.product_name,
                    unitPrice=item.unit_price,
                    units=item.quantity,
                    pictureUrl=item.picture_url,
                )
                for item in event.basket.items
            ],
        )
        result = await self._send(IdentifiedCommand(command=command, id=event.request_id))
        logger.info("create_order_command_result", result=bool(result), request_id=str(event.request_id))

    async def on_grace_period_confirmed(self, event) -> None:
        assert isinstance(event, GracePeriodConfirmedIntegrationEvent)
        await self._send(SetAwaitingValidationOrderStatusCommand(orderNumber=event.order_id))

    async def on_order_stock_confirmed(self, event) -> None:
        assert isinstance(event, OrderStockConfirmedIntegrationEvent)
        await self._send(SetStockConfirmedOrderStatusCommand(orderNumber=event.order_id))

    async def on_order_stock_rejected(self, event) -> None:
        assert isinstance(event, OrderStockRejectedIntegrationEvent)
        rejected = [item.product_id for item in event.order_stock_items if not item.has_stock]
        await self._send(SetStockRejectedOrderStatusCommand(orderNumber=event.order_id, orderStockItems=rejected))

    async def on_order_payment_succeeded(self, event) -> None:
        assert isinstance(event, OrderPaymentSucceededIntegrationEvent)
        await self._send(SetPaidOrderStatusCommand(orderNumber=event.order_id))

    async def on_order_payment_failed(self, event) -> None:
        assert isinstance(event, OrderPaymentFailedIntegrationEvent)
        await self._send(CancelOrderCommand(orderNumber=event.order_id))
