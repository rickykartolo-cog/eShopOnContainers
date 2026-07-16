"""Programmatic construction of the Locations OpenAPI document, mirroring the
Swashbuckle output frozen in ``contracts/openapi/locations.swagger.json``.

Equality with the golden is asserted in unit tests and by the CI contract gate
against the running service.
"""

from __future__ import annotations

from typing import Any

_REF = "$ref"


def _ref(name: str) -> dict[str, str]:
    return {_REF: f"#/components/schemas/{name}"}


def _content(schema: dict[str, Any]) -> dict[str, Any]:
    return {media: {"schema": schema} for media in ("text/plain", "application/json", "text/json")}


def _security() -> list[dict[str, Any]]:
    return [{"oauth2": ["locationsapi"]}]


_AUTH_ERRORS: dict[str, Any] = {
    "401": {"description": "Unauthorized"},
    "403": {"description": "Forbidden"},
}


def build_document(identity_url_external: str | None = None) -> dict[str, Any]:
    identity = (identity_url_external or "http://localhost:5105").rstrip("/")
    locations_array = {"type": "array", "items": _ref("Locations"), "nullable": True}

    paths: dict[str, Any] = {
        "/api/v1/Locations/user/{userId}": {
            "get": {
                "tags": ["Locations"],
                "parameters": [
                    {
                        "name": "userId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string", "format": "uuid"},
                    }
                ],
                "responses": {
                    "200": {"description": "Success", "content": _content(_ref("UserLocation"))},
                    **_AUTH_ERRORS,
                },
                "security": _security(),
            }
        },
        "/api/v1/Locations": {
            "get": {
                "tags": ["Locations"],
                "responses": {
                    "200": {"description": "Success", "content": _content(locations_array)},
                    **_AUTH_ERRORS,
                },
                "security": _security(),
            },
            "post": {
                "tags": ["Locations"],
                "requestBody": {
                    "content": {
                        media: {"schema": _ref("LocationRequest")}
                        for media in (
                            "application/json-patch+json",
                            "application/json",
                            "text/json",
                            "application/*+json",
                        )
                    }
                },
                "responses": {
                    "200": {"description": "Success"},
                    "400": {"description": "Bad Request", "content": _content(_ref("ProblemDetails"))},
                    **_AUTH_ERRORS,
                },
                "security": _security(),
            },
        },
        "/api/v1/Locations/{locationId}": {
            "get": {
                "tags": ["Locations"],
                "parameters": [
                    {
                        "name": "locationId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer", "format": "int32"},
                    }
                ],
                "responses": {
                    "200": {"description": "Success", "content": _content(_ref("Locations"))},
                    **_AUTH_ERRORS,
                },
                "security": _security(),
            }
        },
    }

    schemas: dict[str, Any] = {
        "UserLocation": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "nullable": True},
                "userId": {"type": "string", "nullable": True},
                "locationId": {"type": "integer", "format": "int32"},
                "updateDate": {"type": "string", "format": "date-time"},
            },
            "nullable": True,
        },
        "LocationPoint": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "nullable": True, "readOnly": True},
                "coordinates": {
                    "type": "array",
                    "items": {"type": "number", "format": "double"},
                    "nullable": True,
                    "readOnly": True,
                },
            },
            "nullable": True,
        },
        "LocationPolygon": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "nullable": True, "readOnly": True},
                "coordinates": {
                    "type": "array",
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {"type": "number", "format": "double"},
                            "nullable": True,
                        },
                        "nullable": True,
                    },
                    "nullable": True,
                    "readOnly": True,
                },
            },
            "nullable": True,
        },
        "Locations": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "nullable": True},
                "locationId": {"type": "integer", "format": "int32"},
                "code": {"type": "string", "nullable": True},
                "parent_Id": {"type": "string", "nullable": True},
                "description": {"type": "string", "nullable": True},
                "latitude": {"type": "number", "format": "double"},
                "longitude": {"type": "number", "format": "double"},
                "location": _ref("LocationPoint"),
                "polygon": _ref("LocationPolygon"),
            },
            "nullable": True,
        },
        "LocationRequest": {
            "type": "object",
            "properties": {
                "longitude": {"type": "number", "format": "double"},
                "latitude": {"type": "number", "format": "double"},
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
    }

    return {
        "openapi": "3.0.1",
        "info": {
            "title": "eShopOnContainers - Location HTTP API",
            "description": "The Location Microservice HTTP API. This is a Data-Driven/CRUD microservice sample",
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
                            "authorizationUrl": f"{identity}/connect/authorize",
                            "tokenUrl": f"{identity}/connect/token",
                            "scopes": {"locations": "Locations API"},
                        }
                    },
                }
            },
        },
    }
