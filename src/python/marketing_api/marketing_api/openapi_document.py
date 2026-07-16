"""Programmatic construction of the Marketing OpenAPI document, mirroring the
Swashbuckle output frozen in ``contracts/openapi/marketing.swagger.json``.

Built from the same conventions Swashbuckle applies to the .NET controllers
(three response content types, ``ProblemDetails`` error bodies, oauth2 security
requirements from ``AuthorizeCheckOperationFilter``). Equality with the golden
is asserted in unit tests and by the CI contract gate against the running
service.
"""

from __future__ import annotations

from typing import Any

_REF = "$ref"


def _ref(name: str) -> dict[str, str]:
    return {_REF: f"#/components/schemas/{name}"}


def _content(schema: dict[str, Any]) -> dict[str, Any]:
    return {media: {"schema": schema} for media in ("text/plain", "application/json", "text/json")}


def _problem(status: str, description: str) -> tuple[str, dict[str, Any]]:
    return status, {"description": description, "content": _content(_ref("ProblemDetails"))}


def _int_param(name: str, where: str, default: int | None = None, *, required: bool = False) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "integer", "format": "int32"}
    if default is not None:
        schema["default"] = default
    param: dict[str, Any] = {"name": name, "in": where}
    if required:
        param["required"] = True
    param["schema"] = schema
    return param


_SECURITY = [{"oauth2": ["marketingapi"]}]

_AUTH_ERRORS: list[tuple[str, dict[str, Any]]] = [
    ("401", {"description": "Unauthorized"}),
    ("403", {"description": "Forbidden"}),
]

_CAMPAIGN_BODY = {
    "content": {
        media: {"schema": _ref("CampaignDTO")}
        for media in ("application/json-patch+json", "application/json", "text/json", "application/*+json")
    }
}

_LOCATION_BODY = {
    "content": {
        media: {"schema": _ref("UserLocationRuleDTO")}
        for media in ("application/json-patch+json", "application/json", "text/json", "application/*+json")
    }
}


def build_document(identity_url_external: str = "http://localhost:5105") -> dict[str, Any]:
    campaigns_array = {"type": "array", "items": _ref("CampaignDTO"), "nullable": True}
    locations_array = {"type": "array", "items": _ref("UserLocationRuleDTO"), "nullable": True}
    paths: dict[str, Any] = {
        "/api/v1/Campaigns": {
            "get": {
                "tags": ["Campaigns"],
                "responses": dict(
                    [("200", {"description": "Success", "content": _content(campaigns_array)})] + _AUTH_ERRORS
                ),
                "security": _SECURITY,
            },
            "post": {
                "tags": ["Campaigns"],
                "requestBody": _CAMPAIGN_BODY,
                "responses": dict(
                    [_problem("400", "Bad Request"), ("201", {"description": "Success"})] + _AUTH_ERRORS
                ),
                "security": _SECURITY,
            },
        },
        "/api/v1/Campaigns/{id}": {
            "get": {
                "tags": ["Campaigns"],
                "parameters": [_int_param("id", "path", required=True)],
                "responses": dict(
                    [
                        ("200", {"description": "Success", "content": _content(_ref("CampaignDTO"))}),
                        _problem("404", "Not Found"),
                    ]
                    + _AUTH_ERRORS
                ),
                "security": _SECURITY,
            },
            "put": {
                "tags": ["Campaigns"],
                "parameters": [_int_param("id", "path", required=True)],
                "requestBody": _CAMPAIGN_BODY,
                "responses": dict(
                    [
                        _problem("400", "Bad Request"),
                        _problem("404", "Not Found"),
                        ("201", {"description": "Success"}),
                    ]
                    + _AUTH_ERRORS
                ),
                "security": _SECURITY,
            },
            "delete": {
                "tags": ["Campaigns"],
                "parameters": [_int_param("id", "path", required=True)],
                "responses": dict(
                    [
                        _problem("400", "Bad Request"),
                        _problem("404", "Not Found"),
                        ("204", {"description": "Success"}),
                    ]
                    + _AUTH_ERRORS
                ),
                "security": _SECURITY,
            },
        },
        "/api/v1/Campaigns/user": {
            "get": {
                "tags": ["Campaigns"],
                "parameters": [_int_param("pageSize", "query", 10), _int_param("pageIndex", "query", 0)],
                "responses": dict(
                    [
                        (
                            "200",
                            {
                                "description": "Success",
                                "content": _content(_ref("CampaignDTOPaginatedItemsViewModel")),
                            },
                        )
                    ]
                    + _AUTH_ERRORS
                ),
                "security": _SECURITY,
            }
        },
        "/api/v1/campaigns/{campaignId}/locations/{userLocationRuleId}": {
            "get": {
                "tags": ["Locations"],
                "parameters": [
                    _int_param("campaignId", "path", required=True),
                    _int_param("userLocationRuleId", "path", required=True),
                ],
                "responses": dict(
                    [
                        _problem("400", "Bad Request"),
                        _problem("404", "Not Found"),
                        ("200", {"description": "Success", "content": _content(_ref("UserLocationRuleDTO"))}),
                    ]
                    + _AUTH_ERRORS
                ),
                "security": _SECURITY,
            },
            "delete": {
                "tags": ["Locations"],
                "parameters": [
                    _int_param("campaignId", "path", required=True),
                    _int_param("userLocationRuleId", "path", required=True),
                ],
                "responses": dict(
                    [_problem("400", "Bad Request"), _problem("404", "Not Found")] + _AUTH_ERRORS
                ),
                "security": _SECURITY,
            },
        },
        "/api/v1/campaigns/{campaignId}/locations": {
            "get": {
                "tags": ["Locations"],
                "parameters": [_int_param("campaignId", "path", required=True)],
                "responses": dict(
                    [
                        _problem("400", "Bad Request"),
                        ("200", {"description": "Success", "content": _content(locations_array)}),
                    ]
                    + _AUTH_ERRORS
                ),
                "security": _SECURITY,
            },
            "post": {
                "tags": ["Locations"],
                "parameters": [_int_param("campaignId", "path", required=True)],
                "requestBody": _LOCATION_BODY,
                "responses": dict(
                    [_problem("400", "Bad Request"), ("201", {"description": "Success"})] + _AUTH_ERRORS
                ),
                "security": _SECURITY,
            },
        },
        "/api/v1/campaigns/{campaignId}/pic": {
            "get": {
                "tags": ["Pic"],
                "parameters": [_int_param("campaignId", "path", required=True)],
                "responses": {"200": {"description": "Success"}},
            }
        },
    }

    def _str_prop() -> dict[str, Any]:
        return {"type": "string", "nullable": True}

    def _int_prop() -> dict[str, Any]:
        return {"type": "integer", "format": "int32"}

    components = {
        "schemas": {
            "CampaignDTO": {
                "type": "object",
                "properties": {
                    "id": _int_prop(),
                    "name": _str_prop(),
                    "description": _str_prop(),
                    "from": {"type": "string", "format": "date-time"},
                    "to": {"type": "string", "format": "date-time"},
                    "pictureUri": _str_prop(),
                    "detailsUri": _str_prop(),
                },
                "nullable": True,
            },
            "Object": {"type": "object", "nullable": True},
            "ProblemDetails": {
                "type": "object",
                "properties": {
                    "type": _str_prop(),
                    "title": _str_prop(),
                    "status": {"type": "integer", "format": "int32", "nullable": True},
                    "detail": _str_prop(),
                    "instance": _str_prop(),
                    "extensions": {
                        "type": "object",
                        "additionalProperties": _ref("Object"),
                        "nullable": True,
                        "readOnly": True,
                    },
                },
                "additionalProperties": _ref("Object"),
                "nullable": True,
            },
            "CampaignDTOPaginatedItemsViewModel": {
                "type": "object",
                "properties": {
                    "pageIndex": {"type": "integer", "format": "int32", "readOnly": True},
                    "pageSize": {"type": "integer", "format": "int32", "readOnly": True},
                    "count": {"type": "integer", "format": "int64", "readOnly": True},
                    "data": {
                        "type": "array",
                        "items": _ref("CampaignDTO"),
                        "nullable": True,
                        "readOnly": True,
                    },
                },
                "nullable": True,
            },
            "UserLocationRuleDTO": {
                "type": "object",
                "properties": {
                    "id": _int_prop(),
                    "locationId": _int_prop(),
                    "description": _str_prop(),
                },
                "nullable": True,
            },
        },
        "securitySchemes": {
            "oauth2": {
                "type": "oauth2",
                "flows": {
                    "implicit": {
                        "authorizationUrl": f"{identity_url_external}/connect/authorize",
                        "tokenUrl": f"{identity_url_external}/connect/token",
                        "scopes": {"marketing": "Marketing API"},
                    }
                },
            }
        },
    }

    return {
        "openapi": "3.0.1",
        "info": {
            "title": "eShopOnContainers - Marketing HTTP API",
            "description": "The Marketing Service HTTP API",
            "version": "v1",
        },
        "paths": paths,
        "components": components,
    }
