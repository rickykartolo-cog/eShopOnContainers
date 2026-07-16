"""Programmatic construction of the Basket OpenAPI document, mirroring the
Swashbuckle output frozen in ``contracts/openapi/basket.swagger.json``.

Equality with the golden is asserted in unit tests and by the CI contract gate
against the running service.
"""

from __future__ import annotations

from typing import Any

_REF = "$ref"


def _ref(name: str) -> dict[str, str]:
    return {_REF: f"#/components/schemas/{name}"}


def _response_content(schema: dict[str, Any]) -> dict[str, Any]:
    return {media: {"schema": schema} for media in ("text/plain", "application/json", "text/json")}


def _request_body(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": {
            media: {"schema": schema}
            for media in ("application/json-patch+json", "application/json", "text/json", "application/*+json")
        }
    }


_AUTH_RESPONSES = {"401": {"description": "Unauthorized"}, "403": {"description": "Forbidden"}}
_SECURITY = [{"oauth2": ["basketapi"]}]

_ID_PARAM = {
    "name": "id",
    "in": "path",
    "required": True,
    "schema": {"type": "string", "nullable": True},
}

_NULLABLE_STRING = {"type": "string", "nullable": True}


def build_document(identity_url_external: str = "http://localhost:5105") -> dict[str, Any]:
    customer_basket_ok = {
        "200": {"description": "Success", "content": _response_content(_ref("CustomerBasket"))}
    }
    paths: dict[str, Any] = {
        "/api/v1/Basket/{id}": {
            "get": {
                "tags": ["Basket"],
                "parameters": [_ID_PARAM],
                "responses": {**customer_basket_ok, **_AUTH_RESPONSES},
                "security": _SECURITY,
            },
            "delete": {
                "tags": ["Basket"],
                "parameters": [_ID_PARAM],
                "responses": {"200": {"description": "Success"}, **_AUTH_RESPONSES},
                "security": _SECURITY,
            },
        },
        "/api/v1/Basket": {
            "post": {
                "tags": ["Basket"],
                "requestBody": _request_body(_ref("CustomerBasket")),
                "responses": {**customer_basket_ok, **_AUTH_RESPONSES},
                "security": _SECURITY,
            }
        },
        "/api/v1/Basket/checkout": {
            "post": {
                "tags": ["Basket"],
                "parameters": [
                    {"name": "x-requestid", "in": "header", "schema": _NULLABLE_STRING}
                ],
                "requestBody": _request_body(_ref("BasketCheckout")),
                "responses": {
                    "202": {"description": "Success"},
                    "400": {
                        "description": "Bad Request",
                        "content": _response_content(_ref("ProblemDetails")),
                    },
                    **_AUTH_RESPONSES,
                },
                "security": _SECURITY,
            }
        },
    }

    schemas: dict[str, Any] = {
        "BasketItem": {
            "type": "object",
            "properties": {
                "id": _NULLABLE_STRING,
                "productId": {"type": "integer", "format": "int32"},
                "productName": _NULLABLE_STRING,
                "unitPrice": {"type": "number", "format": "double"},
                "oldUnitPrice": {"type": "number", "format": "double"},
                "quantity": {"type": "integer", "format": "int32"},
                "pictureUrl": _NULLABLE_STRING,
            },
            "nullable": True,
        },
        "CustomerBasket": {
            "type": "object",
            "properties": {
                "buyerId": _NULLABLE_STRING,
                "items": {"type": "array", "items": _ref("BasketItem"), "nullable": True},
            },
            "nullable": True,
        },
        "BasketCheckout": {
            "type": "object",
            "properties": {
                "city": _NULLABLE_STRING,
                "street": _NULLABLE_STRING,
                "state": _NULLABLE_STRING,
                "country": _NULLABLE_STRING,
                "zipCode": _NULLABLE_STRING,
                "cardNumber": _NULLABLE_STRING,
                "cardHolderName": _NULLABLE_STRING,
                "cardExpiration": {"type": "string", "format": "date-time"},
                "cardSecurityNumber": _NULLABLE_STRING,
                "cardTypeId": {"type": "integer", "format": "int32"},
                "buyer": _NULLABLE_STRING,
                "requestId": {"type": "string", "format": "uuid"},
            },
            "nullable": True,
        },
        "Object": {"type": "object", "nullable": True},
        "ProblemDetails": {
            "type": "object",
            "properties": {
                "type": _NULLABLE_STRING,
                "title": _NULLABLE_STRING,
                "status": {"type": "integer", "format": "int32", "nullable": True},
                "detail": _NULLABLE_STRING,
                "instance": _NULLABLE_STRING,
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
    }

    return {
        "openapi": "3.0.1",
        "info": {
            "title": "eShopOnContainers - Basket HTTP API",
            "description": "The Basket Service HTTP API",
            "version": "v1",
        },
        "paths": paths,
        "components": {
            "schemas": schemas,
            "securitySchemes": {
                "oauth2": {
                    "type": "oauth2",
                    "flows": {
                        "implicit": {
                            "authorizationUrl": f"{identity_url_external}/connect/authorize",
                            "tokenUrl": f"{identity_url_external}/connect/token",
                            "scopes": {"basket": "Basket API"},
                        }
                    },
                }
            },
        },
    }
