"""HTTP routes preserving Marketing.API's frozen contract (master prompt §4.6).

Semantics ported from ``CampaignsController``/``LocationsController``/
``PicController``, including ASP.NET routing behavior: int route-constraint
mismatches produce 404, model-binding failures produce the 400
``ValidationProblemDetails``, and empty results (``NotFound()``/``BadRequest()``/
``NoContent()``) have empty bodies. All campaign/location routes require the
authenticated ``sub`` claim (audience ``marketing``); the pic route is anonymous.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast

from eshop_common.events import dumps_newtonsoft
from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from marketing_api.models import Campaign, UserLocationRule, campaign_hilo, rule_hilo
from marketing_api.read_model import MarketingDataRepository
from marketing_api.serialization import (
    build_details_uri,
    campaign_payload,
    get_uri_placeholder,
    json_response,
    paginated_payload,
    parse_dotnet_datetime,
    user_location_rule_payload,
)
from marketing_api.settings import MarketingSettings

router = APIRouter()

DOTNET_MIN_DATETIME = datetime(1, 1, 1)


def _session(request: Request) -> AsyncSession:
    return request.state.session


def _settings(request: Request) -> MarketingSettings:
    return request.app.state.marketing_settings


def _repository(request: Request) -> MarketingDataRepository:
    return request.app.state.marketing_data_repository


def _user(request: Request) -> str | None:
    return getattr(request.state, "user_sub", None)


def _challenge() -> Response:
    return Response(status_code=401, headers={"WWW-Authenticate": "Bearer"})


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


def _query_int(request: Request, name: str, default: int) -> int | Response:
    raw = None
    for key, value in request.query_params.items():
        if key.lower() == name.lower():
            raw = value
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return _validation_problem(request, {name: [f"The value '{raw}' is not valid."]})


async def _read_body(request: Request) -> dict[str, Any] | Response:
    try:
        body = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        return _validation_problem(request, {"": ["The input was not valid."]})
    if not isinstance(body, dict):
        return _validation_problem(request, {"": ["The input was not valid."]})
    return {key.lower(): value for key, value in body.items()}


def _parse_body_datetime(body: dict[str, Any], name: str) -> datetime | None:
    """Missing DateTime binds to default(DateTime); invalid text is a binding error."""
    raw = body.get(name)
    if raw is None:
        return DOTNET_MIN_DATETIME
    try:
        return parse_dotnet_datetime(str(raw))
    except ValueError:
        return None


def _campaign_dto(campaign: Campaign, request: Request) -> dict[str, Any]:
    settings = _settings(request)
    user_id = _user(request) or ""
    return campaign_payload(
        campaign,
        get_uri_placeholder(campaign, settings.pic_base_url, settings.azure_storage_enabled),
        build_details_uri(campaign.Id, user_id, settings.campaign_detail_function_uri),
    )


def _created(request: Request, location_path: str) -> Response:
    base = str(request.base_url).rstrip("/")
    root_path = request.scope.get("root_path", "")
    return Response(status_code=201, headers={"Location": f"{base}{root_path}{location_path}"})


@router.get("/", include_in_schema=False)
async def home(request: Request) -> Response:
    return RedirectResponse(url=f"{request.scope.get('root_path', '')}/swagger")


@router.get("/api/v1/campaigns")
async def get_all_campaigns(request: Request) -> Response:
    if _user(request) is None:
        return _challenge()
    session = _session(request)
    campaigns = (await session.execute(select(Campaign))).scalars().all()
    return json_response([_campaign_dto(campaign, request) for campaign in campaigns])


@router.get("/api/v1/campaigns/user")
async def get_campaigns_by_user(request: Request) -> Response:
    user_id = _user(request)
    if user_id is None:
        return _challenge()
    page_size = _query_int(request, "pageSize", 10)
    if isinstance(page_size, Response):
        return page_size
    page_index = _query_int(request, "pageIndex", 0)
    if isinstance(page_index, Response):
        return page_index

    session = _session(request)
    marketing_data = await _repository(request).get(str(user_id))

    dto_list: list[dict[str, Any]] = []
    if marketing_data is not None:
        location_ids = [location.LocationId for location in marketing_data.Locations]
        now = datetime.now()
        campaigns = (
            await session.execute(
                select(Campaign)
                .join(UserLocationRule, UserLocationRule.CampaignId == Campaign.Id)
                .where(
                    Campaign.From <= now,
                    Campaign.To >= now,
                    UserLocationRule.LocationId.in_(location_ids),
                )
            )
        ).scalars().all()
        dto_list = [_campaign_dto(campaign, request) for campaign in campaigns]

    total_items = len(dto_list)
    dto_list = dto_list[page_size * page_index:page_size * page_index + page_size]
    return json_response(paginated_payload(page_index, page_size, total_items, dto_list))


@router.get("/api/v1/campaigns/{campaign_id}")
async def get_campaign_by_id(request: Request, campaign_id: str) -> Response:
    try:
        parsed = int(campaign_id)
    except ValueError:
        return Response(status_code=404)  # {id:int} constraint mismatch
    if _user(request) is None:
        return _challenge()
    session = _session(request)
    campaign = (
        await session.execute(select(Campaign).where(Campaign.Id == parsed))
    ).scalar_one_or_none()
    if campaign is None:
        return Response(status_code=404)
    return json_response(_campaign_dto(campaign, request))


@router.post("/api/v1/campaigns")
async def create_campaign(request: Request) -> Response:
    if _user(request) is None:
        return _challenge()
    body = await _read_body(request)
    if isinstance(body, Response):
        return body
    from_date = _parse_body_datetime(body, "from")
    to_date = _parse_body_datetime(body, "to")
    if from_date is None or to_date is None:
        return _validation_problem(request, {"": ["The input was not valid."]})

    session = _session(request)
    campaign_id = int(body.get("id") or 0) or await campaign_hilo.next_id(session)
    campaign = Campaign(
        Id=campaign_id,
        Name=cast(str, body.get("name")),
        Description=cast(str, body.get("description")),
        From=from_date,
        To=to_date,
        PictureUri=cast(str, body.get("pictureuri")),
    )
    session.add(campaign)
    await session.commit()
    return _created(request, f"/api/v1/Campaigns/{campaign.Id}")


@router.put("/api/v1/campaigns/{campaign_id}")
async def update_campaign(request: Request, campaign_id: str) -> Response:
    try:
        parsed = int(campaign_id)
    except ValueError:
        return Response(status_code=404)  # {id:int} constraint mismatch
    if _user(request) is None:
        return _challenge()
    if parsed < 1:
        return Response(status_code=400)
    body = await _read_body(request)
    if isinstance(body, Response):
        return body
    from_date = _parse_body_datetime(body, "from")
    to_date = _parse_body_datetime(body, "to")
    if from_date is None or to_date is None:
        return _validation_problem(request, {"": ["The input was not valid."]})

    session = _session(request)
    campaign = (
        await session.execute(select(Campaign).where(Campaign.Id == parsed))
    ).scalar_one_or_none()
    if campaign is None:
        return Response(status_code=404)

    campaign.Name = cast(str, body.get("name"))
    campaign.Description = cast(str, body.get("description"))
    campaign.From = from_date
    campaign.To = to_date
    campaign.PictureUri = cast(str, body.get("pictureuri"))
    await session.commit()
    return _created(request, f"/api/v1/Campaigns/{campaign.Id}")


@router.delete("/api/v1/campaigns/{campaign_id}")
async def delete_campaign(request: Request, campaign_id: str) -> Response:
    try:
        parsed = int(campaign_id)
    except ValueError:
        return Response(status_code=404)  # {id:int} constraint mismatch
    if _user(request) is None:
        return _challenge()
    if parsed < 1:
        return Response(status_code=400)
    session = _session(request)
    campaign = (
        await session.execute(select(Campaign).where(Campaign.Id == parsed))
    ).scalar_one_or_none()
    if campaign is None:
        return Response(status_code=404)
    await session.delete(campaign)
    await session.commit()
    return Response(status_code=204)


def _parse_route_ids(*values: str) -> list[int] | None:
    parsed: list[int] = []
    for value in values:
        try:
            parsed.append(int(value))
        except ValueError:
            return None
    return parsed


@router.get("/api/v1/campaigns/{campaign_id}/locations")
async def get_all_locations_by_campaign(request: Request, campaign_id: str) -> Response:
    ids = _parse_route_ids(campaign_id)
    if ids is None:
        return Response(status_code=404)  # {campaignId:int} constraint mismatch
    if _user(request) is None:
        return _challenge()
    if ids[0] < 1:
        return Response(status_code=400)
    session = _session(request)
    rules = (
        await session.execute(select(UserLocationRule).where(UserLocationRule.CampaignId == ids[0]))
    ).scalars().all()
    return json_response([user_location_rule_payload(rule) for rule in rules])


@router.get("/api/v1/campaigns/{campaign_id}/locations/{user_location_rule_id}")
async def get_location_by_campaign_and_rule_id(
    request: Request, campaign_id: str, user_location_rule_id: str
) -> Response:
    ids = _parse_route_ids(campaign_id, user_location_rule_id)
    if ids is None:
        return Response(status_code=404)
    if _user(request) is None:
        return _challenge()
    if ids[0] < 1 or ids[1] < 1:
        return Response(status_code=400)
    session = _session(request)
    rule = (
        await session.execute(
            select(UserLocationRule).where(
                UserLocationRule.CampaignId == ids[0], UserLocationRule.Id == ids[1]
            )
        )
    ).scalar_one_or_none()
    if rule is None:
        return Response(status_code=404)
    return json_response(user_location_rule_payload(rule))


@router.post("/api/v1/campaigns/{campaign_id}/locations")
async def create_location(request: Request, campaign_id: str) -> Response:
    ids = _parse_route_ids(campaign_id)
    if ids is None:
        return Response(status_code=404)
    if _user(request) is None:
        return _challenge()
    if ids[0] < 1:
        return Response(status_code=400)
    body = await _read_body(request)
    if isinstance(body, Response):
        return body

    session = _session(request)
    rule_id = int(body.get("id") or 0) or await rule_hilo.next_id(session)
    rule = UserLocationRule(
        Id=rule_id,
        CampaignId=ids[0],
        Description=cast(str, body.get("description")),
        LocationId=int(body.get("locationid") or 0),
    )
    session.add(rule)
    await session.commit()
    return _created(request, f"/api/v1/campaigns/{ids[0]}/locations/{rule.Id}")


@router.delete("/api/v1/campaigns/{campaign_id}/locations/{user_location_rule_id}")
async def delete_location(request: Request, campaign_id: str, user_location_rule_id: str) -> Response:
    ids = _parse_route_ids(campaign_id, user_location_rule_id)
    if ids is None:
        return Response(status_code=404)
    if _user(request) is None:
        return _challenge()
    if ids[0] < 1 or ids[1] < 1:
        return Response(status_code=400)
    session = _session(request)
    rule = (
        await session.execute(
            select(UserLocationRule).where(
                UserLocationRule.CampaignId == ids[0], UserLocationRule.Id == ids[1]
            )
        )
    ).scalar_one_or_none()
    if rule is None:
        return Response(status_code=404)
    await session.delete(rule)
    await session.commit()
    return Response(status_code=204)


@router.get("/api/v1/campaigns/{campaign_id}/pic")
async def get_image(request: Request, campaign_id: str) -> Response:
    """Anonymous, like ``PicController``: serves ``{webroot}/{campaignId}.png``;
    a missing file is unhandled (500), matching the .NET behavior."""
    try:
        parsed = int(campaign_id)
    except ValueError:
        return Response(status_code=404)  # {campaignId:int} constraint mismatch
    settings = _settings(request)
    buffer = (settings.pics_path / f"{parsed}.png").read_bytes()
    return Response(content=buffer, media_type="image/png")
