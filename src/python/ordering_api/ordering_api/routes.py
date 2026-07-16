"""HTTP routes preserving Ordering.API's frozen contract (master prompt §4.3).

Ports of ``OrdersController``: all routes require a bearer token with audience
``orders``; cancel/ship require a valid non-empty ``x-requestid`` GUID
(otherwise 400) and are idempotent through ``IdentifiedCommand`` + the
``ordering.requests`` table.
"""

from __future__ import annotations

import uuid

import pydantic
import structlog
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ordering_api import queries
from ordering_api.commands import (
    CancelOrderCommand,
    CommandValidationError,
    CreateOrderDraftCommand,
    IdentifiedCommand,
    ShipOrderCommand,
)
from ordering_api.integration import Identity, execute_command_transaction
from ordering_api.models import OrderingDomainException
from ordering_api.serialization import json_response

logger = structlog.get_logger(__name__)

router = APIRouter()


def _session(request: Request) -> AsyncSession:
    return request.state.session


def _identity(request: Request) -> Identity:
    claims = request.state.user
    return Identity(user_id=claims.get("sub"), user_name=claims.get("name"))


async def _authorized(request: Request) -> dict:
    return await request.app.state.jwt_bearer(request)


def _parse_request_id(request: Request) -> uuid.UUID | None:
    raw = request.headers.get("x-requestid", "")
    try:
        guid = uuid.UUID(raw)
    except ValueError:
        return None
    return guid if guid != uuid.UUID(int=0) else None


async def _send_identified(
    request: Request, command: CancelOrderCommand | ShipOrderCommand, request_id: uuid.UUID
) -> bool:
    identified = IdentifiedCommand(command=command, id=request_id)
    try:
        result = await execute_command_transaction(
            _session(request),
            request.app.state.mediator,
            request.app.state.event_bus,
            identified,
            identity=_identity(request),
        )
    except (CommandValidationError, OrderingDomainException) as exc:
        logger.info("command_rejected", reason=str(exc))
        return False
    return bool(result)


@router.put("/api/v1/orders/cancel", dependencies=[Depends(_authorized)])
async def cancel_order(request: Request) -> Response:
    request_id = _parse_request_id(request)
    command_result = False
    if request_id is not None:
        try:
            command = CancelOrderCommand.model_validate_json(await request.body())
        except pydantic.ValidationError:
            return Response(status_code=400)
        command_result = await _send_identified(request, command, request_id)
    if not command_result:
        return Response(status_code=400)
    return Response(status_code=200)


@router.put("/api/v1/orders/ship", dependencies=[Depends(_authorized)])
async def ship_order(request: Request) -> Response:
    request_id = _parse_request_id(request)
    command_result = False
    if request_id is not None:
        try:
            command = ShipOrderCommand.model_validate_json(await request.body())
        except pydantic.ValidationError:
            return Response(status_code=400)
        command_result = await _send_identified(request, command, request_id)
    if not command_result:
        return Response(status_code=400)
    return Response(status_code=200)


@router.get("/api/v1/orders/cardtypes", dependencies=[Depends(_authorized)])
async def card_types(request: Request) -> Response:
    return json_response(await queries.get_card_types(_session(request)))


@router.get("/api/v1/orders/{order_id}", dependencies=[Depends(_authorized)])
async def get_order(request: Request, order_id: str) -> Response:
    try:
        parsed = int(order_id)
    except ValueError:
        return Response(status_code=404)  # {orderId:int} route-constraint mismatch
    try:
        order = await queries.get_order(_session(request), parsed)
    except Exception:
        # Mirrors the .NET catch-all around GetOrderAsync.
        return Response(status_code=404)
    return json_response(order)


@router.get("/api/v1/orders", dependencies=[Depends(_authorized)])
async def get_orders(request: Request) -> Response:
    identity = _identity(request)
    user_id = uuid.UUID(identity.user_id or "")
    orders = await queries.get_orders_from_user(_session(request), user_id)
    return json_response(orders)


@router.post("/api/v1/orders/draft", dependencies=[Depends(_authorized)])
async def create_order_draft(request: Request) -> Response:
    try:
        command = CreateOrderDraftCommand.model_validate_json(await request.body())
    except pydantic.ValidationError:
        return Response(status_code=400)
    draft = await execute_command_transaction(
        _session(request),
        request.app.state.mediator,
        request.app.state.event_bus,
        command,
        identity=_identity(request),
    )
    return json_response(draft)
