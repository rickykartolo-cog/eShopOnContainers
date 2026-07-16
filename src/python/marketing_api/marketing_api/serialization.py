"""HTTP response serialization matching ASP.NET Core 3.1 + AddNewtonsoftJson:
camelCase property names and Newtonsoft ``DateTime`` round-tripping.

``Campaign.From``/``To`` come out of SQL Server ``datetime2`` as Unspecified-kind
values, which Newtonsoft writes without a UTC/offset suffix
(``yyyy-MM-ddTHH:mm:ss.FFFFFFF``); dates are pre-formatted into the payloads."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from eshop_common.events import dumps_newtonsoft
from fastapi import Response

from marketing_api.models import Campaign, Rule


def format_dotnet_datetime(value: datetime) -> str:
    """Newtonsoft output for an Unspecified-kind DateTime: no zone suffix,
    fractional seconds trimmed and omitted when zero."""
    if value.tzinfo is not None:
        value = value.replace(tzinfo=None)
    base = value.strftime("%Y-%m-%dT%H:%M:%S")
    fraction = f"{value.microsecond:06d}0".rstrip("0")
    return f"{base}.{fraction}" if fraction else base


def parse_dotnet_datetime(text: str) -> datetime:
    """Parse ISO-8601 input like Newtonsoft model binding; the wall-clock value is
    kept and stored to ``datetime2`` (which has no kind/offset)."""
    normalized = text[:-1] if text.endswith("Z") else text
    return datetime.fromisoformat(normalized).replace(tzinfo=None)


def campaign_payload(campaign: Campaign, picture_uri: str | None, details_uri: str | None) -> dict[str, Any]:
    """CamelCase ``CampaignDTO`` shape, field-for-field with the .NET DTO."""
    return {
        "id": campaign.Id,
        "name": campaign.Name,
        "description": campaign.Description,
        "from": format_dotnet_datetime(campaign.From),
        "to": format_dotnet_datetime(campaign.To),
        "pictureUri": picture_uri,
        "detailsUri": details_uri,
    }


def user_location_rule_payload(rule: Rule) -> dict[str, Any]:
    """CamelCase ``UserLocationRuleDTO`` shape."""
    return {"id": rule.Id, "locationId": rule.LocationId, "description": rule.Description}


def paginated_payload(page_index: int, page_size: int, count: int, data: list[dict[str, Any]]) -> dict[str, Any]:
    """``PaginatedItemsViewModel<CampaignDTO>`` shape: pageIndex, pageSize, count, data."""
    return {"pageIndex": page_index, "pageSize": page_size, "count": count, "data": data}


def json_response(payload: Any, status_code: int = 200) -> Response:
    return Response(
        content=dumps_newtonsoft(payload),
        status_code=status_code,
        media_type="application/json; charset=utf-8",
    )


def get_uri_placeholder(campaign: Campaign, pic_base_url: str, azure_storage_enabled: bool) -> str:
    """Port of ``CampaignsController.GetUriPlaceholder``."""
    if azure_storage_enabled:
        return pic_base_url + (campaign.PictureName or "")
    return pic_base_url.replace("[0]", str(campaign.Id))


def build_details_uri(campaign_id: int, user_id: str, campaign_detail_function_uri: str) -> str | None:
    """Port of the ``CampaignDetailFunctionUri`` DetailsUri composition."""
    if not campaign_detail_function_uri:
        return None
    return f"{campaign_detail_function_uri}&campaignId={campaign_id}&userId={user_id}"
