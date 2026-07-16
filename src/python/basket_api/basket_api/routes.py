"""HTTP routes preserving Basket.API's frozen contract (master prompt §4.2).

Semantics ported from ``BasketController``: all routes authorized, camelCase
Newtonsoft responses, ``ValidateModelStateFilter``-style 400 bodies
(``{"messages": [...]}``), checkout ``x-requestid`` idempotency-key handling,
and DELETE returning ``200`` with an empty body.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog
from eshop_common.events import dumps_newtonsoft
from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse

from basket_api.auth import user_identity, user_name
from basket_api.events import UserCheckoutAcceptedIntegrationEvent
from basket_api.models import BasketCheckout, BindingError, CustomerBasket
from basket_api.repository import RedisBasketRepository

logger = structlog.get_logger(__name__)

router = APIRouter()


def _json_response(payload: Any, status_code: int = 200) -> Response:
    return Response(
        content=dumps_newtonsoft(payload),
        status_code=status_code,
        media_type="application/json; charset=utf-8",
    )


def _bad_request(messages: list[str]) -> Response:
    """``JsonErrorResponse`` body produced by ``ValidateModelStateFilter``."""
    return _json_response({"messages": messages, "developerMessage": None}, status_code=400)


def _repository(request: Request) -> RedisBasketRepository:
    return request.app.state.repository


async def _authenticate(request: Request) -> dict | Response:
    return await request.app.state.authenticator.authenticate(request)


async def _read_json(request: Request) -> Any:
    body = await request.body()
    return json.loads(body)


@router.get("/_proto/", include_in_schema=False)
async def proto(request: Request) -> Response:
    return PlainTextResponse(request.app.state.proto_path.read_text(encoding="utf-8"))


@router.get("/api/v1/basket/{id}")
async def get_basket_by_id(id: str, request: Request) -> Response:
    claims = await _authenticate(request)
    if isinstance(claims, Response):
        return claims
    basket = await _repository(request).get_basket(id)
    return _json_response((basket or CustomerBasket(BuyerId=id)).http_payload())


@router.post("/api/v1/basket")
async def update_basket(request: Request) -> Response:
    claims = await _authenticate(request)
    if isinstance(claims, Response):
        return claims
    try:
        basket = CustomerBasket.from_loose(await _read_json(request))
    except (BindingError, ValueError) as exc:
        return _bad_request(exc.messages if isinstance(exc, BindingError) else [str(exc)])
    validation_errors = [error for item in basket.items for error in item.validate_units()]
    if validation_errors:
        return _bad_request(validation_errors)
    updated = await _repository(request).update_basket(basket)
    return _json_response(updated.http_payload() if updated is not None else None)


@router.post("/api/v1/basket/checkout")
async def checkout(request: Request) -> Response:
    claims = await _authenticate(request)
    if isinstance(claims, Response):
        return claims
    try:
        basket_checkout = BasketCheckout.from_loose(await _read_json(request))
    except (BindingError, ValueError) as exc:
        return _bad_request(exc.messages if isinstance(exc, BindingError) else [str(exc)])

    user_id = user_identity(claims)

    request_id = basket_checkout.request_id
    raw_header = request.headers.get("x-requestid")
    if raw_header:
        try:
            header_guid = uuid.UUID(raw_header)
            if header_guid.int != 0:
                request_id = header_guid
        except ValueError:
            pass

    basket = await _repository(request).get_basket(user_id)
    if basket is None:
        return Response(status_code=400)

    event = UserCheckoutAcceptedIntegrationEvent(
        UserId=user_id,
        UserName=user_name(claims),
        City=basket_checkout.city,
        Street=basket_checkout.street,
        State=basket_checkout.state,
        Country=basket_checkout.country,
        ZipCode=basket_checkout.zip_code,
        CardNumber=basket_checkout.card_number,
        CardHolderName=basket_checkout.card_holder_name,
        CardExpiration=basket_checkout.card_expiration,
        CardSecurityNumber=basket_checkout.card_security_number,
        CardTypeId=basket_checkout.card_type_id,
        Buyer=basket_checkout.buyer,
        RequestId=request_id,
        Basket=basket,
    )

    # Once the basket is checked out, send the integration event so
    # ordering-api converts the basket to an order; publish failures propagate
    # (500) exactly like the .NET controller's rethrow.
    await request.app.state.event_bus.publish(event)

    return Response(status_code=202)


@router.delete("/api/v1/basket/{id}")
async def delete_basket_by_id(id: str, request: Request) -> Response:
    claims = await _authenticate(request)
    if isinstance(claims, Response):
        return claims
    await _repository(request).delete_basket(id)
    return Response(status_code=200)
