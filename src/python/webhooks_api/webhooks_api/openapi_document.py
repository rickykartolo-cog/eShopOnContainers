"""Programmatic construction of the Webhooks OpenAPI document, mirroring the
Swashbuckle output frozen in ``contracts/openapi/webhooks.swagger.json``.

Built from the same conventions Swashbuckle applies to the .NET controller
(three response content types, ``ProblemDetails`` error bodies, ``$ref``
schemas, the ``AuthorizeCheckOperationFilter`` 401/403 + oauth2 security).
Equality with the golden is asserted in unit tests and by the CI contract gate
against the running service. The oauth2 URLs come from ``IdentityUrlExternal``
(``http://localhost:5105`` in the golden capture).
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


_SECURITY = [{"oauth2": ["webhooksapi"]}]
_AUTH_RESPONSES = [
    ("401", {"description": "Unauthorized"}),
    ("403", {"description": "Forbidden"}),
]

_ID_PARAM = {
    "name": "id",
    "in": "path",
    "required": True,
    "schema": {"type": "integer", "format": "int32"},
}


def build_document(identity_url_external: str = "http://localhost:5105") -> dict[str, Any]:
    subscription_array = {
        "type": "array",
        "items": _ref("WebhookSubscription"),
        "nullable": True,
    }
    request_body = {
        "content": {
            media: {"schema": _ref("WebhookSubscriptionRequest")}
            for media in ("application/json", "text/json", "application/*+json")
        }
    }
    return {
        "openapi": "3.0.1",
        "info": {
            "title": "eShopOnContainers - Webhooks HTTP API",
            "description": "The Webhooks Microservice HTTP API. This is a simple webhooks CRUD registration entrypoint",
            "version": "v1",
        },
        "paths": {
            "/api/v1/Webhooks": {
                "get": {
                    "tags": ["Webhooks"],
                    "responses": dict(
                        [
                            ("200", {"description": "Success", "content": _content(subscription_array)}),
                            *_AUTH_RESPONSES,
                        ]
                    ),
                    "security": _SECURITY,
                },
                "post": {
                    "tags": ["Webhooks"],
                    "requestBody": request_body,
                    "responses": dict(
                        [
                            ("201", {"description": "Success"}),
                            _problem("400", "Bad Request"),
                            _problem("418", "Client Error"),
                            *_AUTH_RESPONSES,
                        ]
                    ),
                    "security": _SECURITY,
                },
            },
            "/api/v1/Webhooks/{id}": {
                "get": {
                    "tags": ["Webhooks"],
                    "parameters": [_ID_PARAM],
                    "responses": dict(
                        [
                            (
                                "200",
                                {"description": "Success", "content": _content(_ref("WebhookSubscription"))},
                            ),
                            _problem("404", "Not Found"),
                            *_AUTH_RESPONSES,
                        ]
                    ),
                    "security": _SECURITY,
                },
                "delete": {
                    "tags": ["Webhooks"],
                    "parameters": [_ID_PARAM],
                    "responses": dict(
                        [
                            ("202", {"description": "Success"}),
                            _problem("404", "Not Found"),
                            *_AUTH_RESPONSES,
                        ]
                    ),
                    "security": _SECURITY,
                },
            },
        },
        "components": {
            "schemas": {
                "WebhookType": {"enum": [1, 2, 3], "type": "integer", "format": "int32"},
                "WebhookSubscription": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "format": "int32"},
                        "type": _ref("WebhookType"),
                        "date": {"type": "string", "format": "date-time"},
                        "destUrl": {"type": "string", "nullable": True},
                        "token": {"type": "string", "nullable": True},
                        "userId": {"type": "string", "nullable": True},
                    },
                    "nullable": True,
                },
                "WebhookSubscriptionRequest": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "nullable": True},
                        "token": {"type": "string", "nullable": True},
                        "event": {"type": "string", "nullable": True},
                        "grantUrl": {"type": "string", "nullable": True},
                    },
                    "nullable": True,
                },
                "Object": {"type": "object", "nullable": True},
                "ProblemDetails": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "nullable": True},
                        "title": {"type": "string", "nullable": True},
                        "status": {"type": "integer", "format": "int32", "nullable": True},
                        "detail": {"type": "string", "nullable": True},
                        "instance": {"type": "string", "nullable": True},
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
            },
            "securitySchemes": {
                "oauth2": {
                    "type": "oauth2",
                    "flows": {
                        "implicit": {
                            "authorizationUrl": f"{identity_url_external}/connect/authorize",
                            "tokenUrl": f"{identity_url_external}/connect/token",
                            "scopes": {"webhooks": "Webhooks API"},
                        }
                    },
                }
            },
        },
    }
