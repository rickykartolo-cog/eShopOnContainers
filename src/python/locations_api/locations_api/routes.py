"""HTTP routes preserving Locations.API's frozen contract (master prompt §4.6).

Semantics ported from ``LocationsController``/``HomeController``, including
ASP.NET behavior: the ``{userId:guid}`` constraint mismatch produces 404,
model-binding failures produce the 400 ``ValidationProblemDetails``, null
action results produce 204 No Content, and domain/unhandled exceptions map to
the ``HttpGlobalExceptionFilter`` 400/500 JSON bodies.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from eshop_common.events import dumps_newtonsoft
from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from locations_api.models import location_payload, user_location_payload
from locations_api.service import LocationDomainException, LocationsService

router = APIRouter()


def json_response(payload: Any, status_code: int = 200) -> Response:
    return Response(
        content=dumps_newtonsoft(payload),
        status_code=status_code,
        media_type="application/json; charset=utf-8",
    )


def _validation_problem(request: Request, errors: dict[str, list[str]]) -> Response:
    payload: dict[str, Any] = {
        "type": "https://tools.ietf.org/html/rfc7231#section-6.5.1",
        "title": "One or more validation errors occurred.",
        "status": 400,
        "detail": "Please refer to the errors property for additional details.",
        "instance": request.url.path,
        "errors": errors,
    }
    return Response(content=dumps_newtonsoft(payload), status_code=400, media_type="application/problem+json")


def _error_response(messages: list[str], status_code: int) -> Response:
    # HttpGlobalExceptionFilter's JsonErrorResponse, camelCased by AddNewtonsoftJson.
    return json_response({"messages": messages, "developerMessage": None}, status_code=status_code)


def _service(request: Request) -> LocationsService:
    return request.app.state.locations_service


async def _authenticate(request: Request) -> str:
    """Enforce [Authorize] and resolve the ``sub`` claim like IdentityService."""
    return await request.app.state.authenticate(request)


@router.get("/", include_in_schema=False)
async def home(request: Request) -> Response:
    return RedirectResponse(url=f"{request.scope.get('root_path', '')}/swagger")


@router.get("/api/v1/locations/user/{user_id}")
async def get_user_location(request: Request, user_id: str) -> Response:
    await _authenticate(request)
    try:
        parsed = uuid.UUID(user_id)
    except ValueError:
        return Response(status_code=404)  # {userId:guid} constraint mismatch
    user_location = await _service(request).get_user_location(str(parsed))
    if user_location is None:
        return Response(status_code=204)  # null ActionResult<T> -> NoContent
    return json_response(user_location_payload(user_location))


@router.get("/api/v1/locations")
async def get_all_locations(request: Request) -> Response:
    await _authenticate(request)
    locations = await _service(request).get_all_locations()
    return json_response([location_payload(location) for location in locations])


@router.get("/api/v1/locations/{location_id}")
async def get_location(request: Request, location_id: str) -> Response:
    await _authenticate(request)
    try:
        parsed = int(location_id)
    except ValueError:
        # `{locationId}` has no route constraint: binding failure -> 400 problem body.
        return _validation_problem(request, {"locationId": [f"The value '{location_id}' is not valid."]})
    location = await _service(request).get_location(parsed)
    if location is None:
        return Response(status_code=204)  # null ActionResult<T> -> NoContent
    return json_response(location_payload(location))


@router.post("/api/v1/locations")
async def create_or_update_user_location(request: Request) -> Response:
    user_id = await _authenticate(request)
    body = await _read_location_request(request)
    if isinstance(body, Response):
        return body
    longitude, latitude = body

    try:
        result = await _service(request).add_or_update_user_location(user_id, longitude, latitude)
    except LocationDomainException as exc:
        return _error_response([str(exc)], status_code=400)
    except Exception:
        # Matches HttpGlobalExceptionFilter's generic 500 body (e.g. the position
        # is outside every seeded region and list index 0 does not exist).
        return _error_response(["An error occur.Try it again."], status_code=500)

    if not result:
        return Response(status_code=400)
    return Response(status_code=200)


async def _read_location_request(request: Request) -> tuple[float, float] | Response:
    """Newtonsoft model binding for ``LocationRequest``: case-insensitive names,
    missing members default to 0, malformed bodies produce the 400 problem body."""
    try:
        body = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        return _validation_problem(request, {"": ["The input was not valid."]})
    if body is None:
        body = {}
    if not isinstance(body, dict):
        return _validation_problem(request, {"": ["The input was not valid."]})
    values = {key.lower(): value for key, value in body.items()}
    try:
        longitude = float(values.get("longitude", 0.0))
        latitude = float(values.get("latitude", 0.0))
    except (TypeError, ValueError):
        return _validation_problem(request, {"": ["The input was not valid."]})
    return longitude, latitude
