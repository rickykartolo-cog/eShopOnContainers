"""Command + domain-event handlers, ports of ``Ordering.API/Application``.

Each handler mirrors its .NET counterpart exactly (result values, duplicate
request semantics, description strings, simulated stock/payment delays).
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

import structlog
from sqlalchemy import select

from ordering_api.commands import (
    CancelOrderCommand,
    CreateOrderCommand,
    CreateOrderDraftCommand,
    IdentifiedCommand,
    SetAwaitingValidationOrderStatusCommand,
    SetPaidOrderStatusCommand,
    SetStockConfirmedOrderStatusCommand,
    SetStockRejectedOrderStatusCommand,
    ShipOrderCommand,
)
from ordering_api.events import (
    OrderStartedIntegrationEvent,
    OrderStatusChangedToAwaitingValidationIntegrationEvent,
    OrderStatusChangedToCancelledIntegrationEvent,
    OrderStatusChangedToPaidIntegrationEvent,
    OrderStatusChangedToShippedIntegrationEvent,
    OrderStatusChangedToStockConfirmedIntegrationEvent,
    OrderStatusChangedToSubmittedIntegrationEvent,
    OrderStockItem,
)
from ordering_api.integration import CommandContext, save_entities
from ordering_api.mediator import Mediator
from ordering_api.models import (
    Address,
    Buyer,
    BuyerAndPaymentMethodVerifiedDomainEvent,
    ClientRequest,
    Order,
    OrderCancelledDomainEvent,
    OrderingDomainException,
    OrderShippedDomainEvent,
    OrderStartedDomainEvent,
    OrderStatusChangedToAwaitingValidationDomainEvent,
    OrderStatusChangedToPaidDomainEvent,
    OrderStatusChangedToStockConfirmedDomainEvent,
    buyer_hilo,
    order_hilo,
    order_item_hilo,
    payment_hilo,
)

logger = structlog.get_logger(__name__)

# Matches the Task.Delay(10000) "simulated work time" in the .NET stock/paid handlers.
SIMULATED_WORK_SECONDS = 10.0


# --- Repositories (ports of OrderRepository / BuyerRepository) ---


async def get_order(ctx: CommandContext, order_id: int) -> Order | None:
    order = await ctx.session.get(Order, order_id)
    if order is None:
        order = next(
            (o for o in ctx.session.new if isinstance(o, Order) and o.Id == order_id), None
        )
    return order


async def add_order(ctx: CommandContext, order: Order) -> None:
    order.Id = await order_hilo.next_id(ctx.session)
    for item in order.order_items:
        item.Id = await order_item_hilo.next_id(ctx.session)
        item.OrderId = order.Id
    ctx.session.add(order)


async def find_buyer(ctx: CommandContext, identity_guid: str) -> Buyer | None:
    result = await ctx.session.execute(select(Buyer).where(Buyer.IdentityGuid == identity_guid))
    return result.scalars().first()


async def find_buyer_by_id(ctx: CommandContext, buyer_id: int) -> Buyer | None:
    return await ctx.session.get(Buyer, buyer_id)


# --- Idempotency (port of RequestManager / IdentifiedCommandHandler) ---


async def request_exists(ctx: CommandContext, request_id: uuid.UUID) -> bool:
    return await ctx.session.get(ClientRequest, request_id) is not None


async def create_request_for_command(
    ctx: CommandContext, request_id: uuid.UUID, command_name: str
) -> None:
    if await request_exists(ctx, request_id):
        raise OrderingDomainException(f"Request with {request_id} already exists")
    ctx.session.add(ClientRequest(Id=request_id, Name=command_name, Time=datetime.utcnow()))
    await ctx.session.flush()


async def handle_identified_command(
    message: IdentifiedCommand, ctx: CommandContext
) -> bool:
    """Duplicate requests return True (ignored) for all Ordering commands; failures
    of the inner command return the default (False), matching the .NET handler."""
    if await request_exists(ctx, message.id):
        return True
    await create_request_for_command(ctx, message.id, type(message.command).__name__)
    try:
        return bool(await ctx.mediator.send(message.command, ctx))
    except Exception:
        logger.exception("identified_command_failed", request_id=str(message.id))
        # In .NET the request row was already committed by its own SaveChangesAsync
        # and the failed handler's un-saved mutations were discarded; mirror that by
        # rolling back and re-recording only the request row.
        await ctx.session.rollback()
        ctx.session.add(
            ClientRequest(Id=message.id, Name=type(message.command).__name__, Time=datetime.utcnow())
        )
        return False


# --- Command handlers ---


async def handle_create_order(message: CreateOrderCommand, ctx: CommandContext) -> bool:
    order_started = OrderStartedIntegrationEvent(UserId=message.user_id or "")
    await ctx.integration_events.add_and_save_event(order_started)

    address = Address(message.street, message.city, message.state, message.country, message.zip_code)
    order = Order.create(
        message.user_id or "",
        message.user_name,
        address,
        message.card_type_id,
        message.card_number,
        message.card_security_number,
        message.card_holder_name,
        message.card_expiration,
    )
    for item in message.order_items:
        order.add_order_item(
            item.product_id,
            item.product_name,
            item.unit_price,
            item.discount,
            item.picture_url,
            item.units,
        )
    await add_order(ctx, order)
    return await save_entities(ctx)


async def handle_create_order_draft(message: CreateOrderDraftCommand, ctx: CommandContext) -> dict:
    order = Order.new_draft()
    for item in message.items:
        dto = _basket_item_to_order_item_dto(item)
        order.add_order_item(
            dto["productId"],
            dto["productName"],
            dto["unitPrice"],
            dto["discount"],
            dto["pictureUrl"],
            dto["units"],
        )
    return order_draft_dto_from_order(order)


async def handle_cancel_order(command: CancelOrderCommand, ctx: CommandContext) -> bool:
    order = await get_order(ctx, command.order_number)
    if order is None:
        return False
    order.set_cancelled_status()
    return await save_entities(ctx)


async def handle_ship_order(command: ShipOrderCommand, ctx: CommandContext) -> bool:
    order = await get_order(ctx, command.order_number)
    if order is None:
        return False
    order.set_shipped_status()
    return await save_entities(ctx)


async def handle_set_awaiting_validation(
    command: SetAwaitingValidationOrderStatusCommand, ctx: CommandContext
) -> bool:
    order = await get_order(ctx, command.order_number)
    if order is None:
        return False
    order.set_awaiting_validation_status()
    return await save_entities(ctx)


async def handle_set_stock_confirmed(
    command: SetStockConfirmedOrderStatusCommand, ctx: CommandContext
) -> bool:
    await asyncio.sleep(SIMULATED_WORK_SECONDS)
    order = await get_order(ctx, command.order_number)
    if order is None:
        return False
    order.set_stock_confirmed_status()
    return await save_entities(ctx)


async def handle_set_stock_rejected(
    command: SetStockRejectedOrderStatusCommand, ctx: CommandContext
) -> bool:
    await asyncio.sleep(SIMULATED_WORK_SECONDS)
    order = await get_order(ctx, command.order_number)
    if order is None:
        return False
    order.set_cancelled_status_when_stock_is_rejected(command.order_stock_items)
    return await save_entities(ctx)


async def handle_set_paid(command: SetPaidOrderStatusCommand, ctx: CommandContext) -> bool:
    await asyncio.sleep(SIMULATED_WORK_SECONDS)
    order = await get_order(ctx, command.order_number)
    if order is None:
        return False
    order.set_paid_status()
    return await save_entities(ctx)


# --- Domain-event handlers ---


async def on_order_started(event: OrderStartedDomainEvent, ctx: CommandContext) -> None:
    """Port of ``ValidateOrAddBuyerAggregateWhenOrderStartedDomainEventHandler``."""
    card_type_id = event.card_type_id if event.card_type_id != 0 else 1
    buyer = await find_buyer(ctx, event.user_id)
    buyer_existed = buyer is not None
    if buyer is None:
        buyer = Buyer(event.user_id, event.user_name)
        buyer.Id = await buyer_hilo.next_id(ctx.session)
        ctx.session.add(buyer)

    payment = buyer.verify_or_add_payment_method(
        card_type_id,
        f"Payment Method on {datetime.utcnow()}",
        event.card_number,
        event.card_security_number,
        event.card_holder_name,
        event.card_expiration,
        event.order.Id,
    )
    if payment.Id is None:
        payment.Id = await payment_hilo.next_id(ctx.session)
        payment.BuyerId = buyer.Id
    await save_entities(ctx)

    submitted = OrderStatusChangedToSubmittedIntegrationEvent(
        OrderId=event.order.Id,
        OrderStatus=event.order.status_name,
        BuyerName=buyer.Name,
    )
    await ctx.integration_events.add_and_save_event(submitted)
    logger.info("buyer_verified", buyer_id=buyer.Id, order_id=event.order.Id, existed=buyer_existed)


async def on_buyer_payment_verified(
    event: BuyerAndPaymentMethodVerifiedDomainEvent, ctx: CommandContext
) -> None:
    """Port of ``UpdateOrderWhenBuyerAndPaymentMethodVerifiedDomainEventHandler``."""
    order = await get_order(ctx, event.order_id)
    if order is not None:
        order.set_buyer_id(event.buyer.Id)
        order.set_payment_id(event.payment.Id)


async def on_awaiting_validation(
    event: OrderStatusChangedToAwaitingValidationDomainEvent, ctx: CommandContext
) -> None:
    order = await get_order(ctx, event.order_id)
    assert order is not None
    buyer = await find_buyer_by_id(ctx, order.BuyerId) if order.BuyerId else None
    stock_items = [
        OrderStockItem(ProductId=item.ProductId, Units=item.get_units())
        for item in event.order_items
    ]
    integration_event = OrderStatusChangedToAwaitingValidationIntegrationEvent(
        OrderId=order.Id,
        OrderStatus=order.status_name,
        BuyerName=buyer.Name if buyer else None,
        OrderStockItems=stock_items,
    )
    await ctx.integration_events.add_and_save_event(integration_event)


async def on_stock_confirmed(
    event: OrderStatusChangedToStockConfirmedDomainEvent, ctx: CommandContext
) -> None:
    order = await get_order(ctx, event.order_id)
    assert order is not None
    buyer = await find_buyer_by_id(ctx, order.BuyerId) if order.BuyerId else None
    integration_event = OrderStatusChangedToStockConfirmedIntegrationEvent(
        OrderId=order.Id,
        OrderStatus=order.status_name,
        BuyerName=buyer.Name if buyer else None,
    )
    await ctx.integration_events.add_and_save_event(integration_event)


async def on_paid(event: OrderStatusChangedToPaidDomainEvent, ctx: CommandContext) -> None:
    order = await get_order(ctx, event.order_id)
    assert order is not None
    buyer = await find_buyer_by_id(ctx, order.BuyerId) if order.BuyerId else None
    stock_items = [
        OrderStockItem(ProductId=item.ProductId, Units=item.get_units())
        for item in event.order_items
    ]
    integration_event = OrderStatusChangedToPaidIntegrationEvent(
        OrderId=event.order_id,
        OrderStatus=order.status_name,
        BuyerName=buyer.Name if buyer else None,
        OrderStockItems=stock_items,
    )
    await ctx.integration_events.add_and_save_event(integration_event)


async def on_shipped(event: OrderShippedDomainEvent, ctx: CommandContext) -> None:
    order = await get_order(ctx, event.order.Id)
    assert order is not None
    buyer = await find_buyer_by_id(ctx, order.BuyerId) if order.BuyerId else None
    integration_event = OrderStatusChangedToShippedIntegrationEvent(
        OrderId=order.Id,
        OrderStatus=order.status_name,
        BuyerName=buyer.Name if buyer else None,
    )
    await ctx.integration_events.add_and_save_event(integration_event)


async def on_cancelled(event: OrderCancelledDomainEvent, ctx: CommandContext) -> None:
    order = await get_order(ctx, event.order.Id)
    assert order is not None
    buyer = await find_buyer_by_id(ctx, order.BuyerId) if order.BuyerId else None
    integration_event = OrderStatusChangedToCancelledIntegrationEvent(
        OrderId=order.Id,
        OrderStatus=order.status_name,
        BuyerName=buyer.Name if buyer else None,
    )
    await ctx.integration_events.add_and_save_event(integration_event)


# --- DTO mapping (ports of BasketItemExtensions / OrderDraftDTO.FromOrder) ---


def _basket_item_to_order_item_dto(item) -> dict:
    return {
        "productId": item.product_id,
        "productName": item.product_name,
        "unitPrice": item.unit_price,
        "discount": 0,
        "pictureUrl": item.picture_url,
        "units": item.quantity,
    }


def order_draft_dto_from_order(order: Order) -> dict:
    return {
        "orderItems": [
            {
                "discount": item.get_current_discount(),
                "productId": item.ProductId,
                "unitPrice": item.get_unit_price(),
                "pictureUrl": item.get_picture_uri(),
                "units": item.get_units(),
                "productName": item.get_order_item_product_name(),
            }
            for item in order.order_items
        ],
        "total": order.get_total(),
    }


def build_mediator() -> Mediator:
    mediator = Mediator()
    mediator.register_command(IdentifiedCommand, handle_identified_command)
    mediator.register_command(CreateOrderCommand, handle_create_order)
    mediator.register_command(CreateOrderDraftCommand, handle_create_order_draft)
    mediator.register_command(CancelOrderCommand, handle_cancel_order)
    mediator.register_command(ShipOrderCommand, handle_ship_order)
    mediator.register_command(SetAwaitingValidationOrderStatusCommand, handle_set_awaiting_validation)
    mediator.register_command(SetStockConfirmedOrderStatusCommand, handle_set_stock_confirmed)
    mediator.register_command(SetStockRejectedOrderStatusCommand, handle_set_stock_rejected)
    mediator.register_command(SetPaidOrderStatusCommand, handle_set_paid)

    mediator.register_domain_event(OrderStartedDomainEvent, on_order_started)
    mediator.register_domain_event(BuyerAndPaymentMethodVerifiedDomainEvent, on_buyer_payment_verified)
    mediator.register_domain_event(OrderStatusChangedToAwaitingValidationDomainEvent, on_awaiting_validation)
    mediator.register_domain_event(OrderStatusChangedToStockConfirmedDomainEvent, on_stock_confirmed)
    mediator.register_domain_event(OrderStatusChangedToPaidDomainEvent, on_paid)
    mediator.register_domain_event(OrderShippedDomainEvent, on_shipped)
    mediator.register_domain_event(OrderCancelledDomainEvent, on_cancelled)
    return mediator
