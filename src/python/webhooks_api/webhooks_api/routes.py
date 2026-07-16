"""HTTP routes preserving Webhooks.API's frozen contract (master prompt §4.8).

Semantics ported from ``WebhooksController``/``HomeController``, including
ASP.NET behaviors: ``{id:int}`` constraint mismatches produce 404, the
``[ApiController]`` automatic 400 ``ValidationProblemDetails`` (with ``traceId``),
bare-string results are text/plain, ``Accepted()``/auth challenges have empty
bodies, and subscription ownership is enforced through the token's ``sub`` claim.
"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from webhooks_api.models import WebhookSubscription, WebhookType
from webhooks_api.serialization import json_response, stj_dumps, subscription_payload, text_response

router = APIRouter()


def _validation_problem(errors: dict[str, list[str]]) -> Response:
    """The default `[ApiController]` 400 body (Webhooks does not customize
    `ApiBehaviorOptions`, unlike Catalog)."""
    payload: dict[str, Any] = {
        "type": "https://tools.ietf.org/html/rfc7231#section-6.5.1",
        "title": "One or more validation errors occurred.",
        "status": 400,
        "traceId": f"|{secrets.token_hex(8)}-{secrets.token_hex(8)}.",
        "errors": errors,
    }
    return Response(
        content=stj_dumps(payload),
        status_code=400,
        media_type="application/problem+json; charset=utf-8",
    )


async def _authorize(request: Request) -> str | Response:
    """JWT bearer authentication (authority IdentityUrl, audience ``webhooks``);
    returns the ``sub`` claim (the .NET ``IdentityService.GetUserIdentity``)."""
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})
    validator = request.app.state.jwt_validator
    try:
        claims = await validator.validate(token)
    except Exception:
        return Response(
            status_code=401,
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        )
    # .NET's FindFirst("sub").Value would throw (→ 500) when the claim is absent.
    return claims["sub"]


def _is_well_formed_absolute_uri(value: str | None) -> bool:
    """Approximation of ``Uri.IsWellFormedUriString(value, UriKind.Absolute)``
    for the http(s) URLs this API receives."""
    if not value or any(char.isspace() for char in value):
        return False
    parts = urlsplit(value)
    return bool(parts.scheme) and bool(parts.netloc)


@router.get("/", include_in_schema=False)
async def home(request: Request) -> Response:
    return RedirectResponse(url=f"{request.scope.get('root_path', '')}/swagger", status_code=302)


@router.get("/api/v1/webhooks")
async def list_by_user(request: Request) -> Response:
    user_id = await _authorize(request)
    if isinstance(user_id, Response):
        return user_id
    session = request.state.session
    rows = (
        await session.execute(select(WebhookSubscription).where(WebhookSubscription.UserId == user_id))
    ).scalars().all()
    return json_response([subscription_payload(row) for row in rows])


@router.get("/api/v1/webhooks/{subscription_id}")
async def get_by_user_and_id(request: Request, subscription_id: str) -> Response:
    user_id = await _authorize(request)
    if isinstance(user_id, Response):
        return user_id
    try:
        parsed = int(subscription_id)
    except ValueError:
        return Response(status_code=404)  # {id:int} constraint mismatch
    session = request.state.session
    subscription = (
        await session.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.Id == parsed, WebhookSubscription.UserId == user_id
            )
        )
    ).scalar_one_or_none()
    if subscription is not None:
        return json_response(subscription_payload(subscription))
    return text_response(f"Subscriptions {parsed} not found", status_code=404)


@router.post("/api/v1/webhooks")
async def subscribe_webhook(request: Request) -> Response:
    user_id = await _authorize(request)
    if isinstance(user_id, Response):
        return user_id

    try:
        body = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        return _validation_problem({"$": ["The input does not contain any JSON tokens."]})
    if not isinstance(body, dict):
        return _validation_problem({"$": ["The JSON value could not be converted."]})
    fields = {key.lower(): value for key, value in body.items()}
    url = fields.get("url")
    token = fields.get("token")
    event = fields.get("event")
    grant_url = fields.get("granturl")

    # Port of WebhookSubscriptionRequest.Validate (IValidatableObject).
    errors: dict[str, list[str]] = {}
    if not _is_well_formed_absolute_uri(grant_url):
        errors.setdefault("GrantUrl", []).append("GrantUrl is not valid")
    if not _is_well_formed_absolute_uri(url):
        errors.setdefault("Url", []).append("Url is not valid")
    hook_type = WebhookType.try_parse(event)
    if hook_type is None:
        errors.setdefault("Event", []).append(f"{event if event is not None else ''} is invalid event name")
    if errors or hook_type is None:
        return _validation_problem(errors)

    grant_tester = request.app.state.grant_url_tester
    grant_ok = await grant_tester.test_grant_url(url, grant_url, token or "")
    if not grant_ok:
        return text_response("Grant url can't be validated", status_code=418)

    session = request.state.session
    subscription = WebhookSubscription(
        Date=datetime.now(UTC).replace(tzinfo=UTC),
        DestUrl=url,
        Token=token,
        Type=int(hook_type),
        UserId=user_id,
    )
    session.add(subscription)
    await session.commit()
    base = str(request.base_url).rstrip("/")
    root_path = request.scope.get("root_path", "")
    return json_response(
        subscription_payload(subscription),
        status_code=201,
        headers={"Location": f"{base}{root_path}/api/v1/Webhooks/{subscription.Id}"},
    )


@router.delete("/api/v1/webhooks/{subscription_id}")
async def unsubscribe_webhook(request: Request, subscription_id: str) -> Response:
    user_id = await _authorize(request)
    if isinstance(user_id, Response):
        return user_id
    try:
        parsed = int(subscription_id)
    except ValueError:
        return Response(status_code=404)  # {id:int} constraint mismatch
    session = request.state.session
    subscription = (
        await session.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.Id == parsed, WebhookSubscription.UserId == user_id
            )
        )
    ).scalar_one_or_none()
    if subscription is not None:
        await session.delete(subscription)
        await session.commit()
        return Response(status_code=202)
    return text_response(f"Subscriptions {parsed} not found", status_code=404)
