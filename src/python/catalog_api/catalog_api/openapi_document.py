"""Programmatic construction of the Catalog OpenAPI document, mirroring the
Swashbuckle output frozen in ``contracts/openapi/catalog.swagger.json``.

Built from the same conventions Swashbuckle applies to the .NET controllers
(three response content types, ``ProblemDetails`` error bodies, ``$ref``
schemas). Equality with the golden is asserted byte-for-byte in unit tests and
by the CI contract gate against the running service.
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


def _int_param(name: str, where: str, default: int | None = None, *, required: bool = False,
               nullable: bool = False) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "integer", "format": "int32"}
    if nullable:
        schema["nullable"] = True
    if default is not None:
        schema["default"] = default
    param: dict[str, Any] = {"name": name, "in": where}
    if required:
        param["required"] = True
    param["schema"] = schema
    return param


def _paging_params() -> list[dict[str, Any]]:
    return [_int_param("pageSize", "query", 10), _int_param("pageIndex", "query", 0)]


_PAGINATED_OK = {
    "200": {"description": "Success", "content": _content(_ref("CatalogItemPaginatedItemsViewModel"))}
}

_ITEM_BODY = {
    "content": {
        media: {"schema": _ref("CatalogItem")}
        for media in ("application/json-patch+json", "application/json", "text/json", "application/*+json")
    }
}


def build_document() -> dict[str, Any]:
    items_array = {"type": "array", "items": _ref("CatalogItem"), "nullable": True}
    paths: dict[str, Any] = {
        "/api/v1/Catalog/items": {
            "get": {
                "tags": ["Catalog"],
                "parameters": _paging_params()
                + [{"name": "ids", "in": "query", "schema": {"type": "string", "nullable": True}}],
                "responses": dict(
                    [
                        ("200", {"description": "Success", "content": _content(items_array)}),
                        _problem("400", "Bad Request"),
                    ]
                ),
            },
            "put": {
                "tags": ["Catalog"],
                "requestBody": _ITEM_BODY,
                "responses": dict([_problem("404", "Not Found"), ("201", {"description": "Success"})]),
            },
            "post": {
                "tags": ["Catalog"],
                "requestBody": _ITEM_BODY,
                "responses": {"201": {"description": "Success"}},
            },
        },
        "/api/v1/Catalog/items/{id}": {
            "get": {
                "tags": ["Catalog"],
                "parameters": [_int_param("id", "path", required=True)],
                "responses": dict(
                    [
                        _problem("404", "Not Found"),
                        _problem("400", "Bad Request"),
                        ("200", {"description": "Success", "content": _content(_ref("CatalogItem"))}),
                    ]
                ),
            }
        },
        "/api/v1/Catalog/items/withname/{name}": {
            "get": {
                "tags": ["Catalog"],
                "parameters": [
                    {
                        "name": "name",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string", "nullable": True},
                    }
                ]
                + _paging_params(),
                "responses": dict(_PAGINATED_OK),
            }
        },
        "/api/v1/Catalog/items/type/{catalogTypeId}/brand/{catalogBrandId}": {
            "get": {
                "tags": ["Catalog"],
                "parameters": [
                    _int_param("catalogTypeId", "path", required=True),
                    _int_param("catalogBrandId", "path", required=True, nullable=True),
                ]
                + _paging_params(),
                "responses": dict(_PAGINATED_OK),
            }
        },
        "/api/v1/Catalog/items/type/all/brand/{catalogBrandId}": {
            "get": {
                "tags": ["Catalog"],
                "parameters": [_int_param("catalogBrandId", "path", required=True, nullable=True)]
                + _paging_params(),
                "responses": dict(_PAGINATED_OK),
            }
        },
        "/api/v1/Catalog/catalogtypes": {
            "get": {
                "tags": ["Catalog"],
                "responses": {
                    "200": {
                        "description": "Success",
                        "content": _content({"type": "array", "items": _ref("CatalogType"), "nullable": True}),
                    }
                },
            }
        },
        "/api/v1/Catalog/catalogbrands": {
            "get": {
                "tags": ["Catalog"],
                "responses": {
                    "200": {
                        "description": "Success",
                        "content": _content({"type": "array", "items": _ref("CatalogBrand"), "nullable": True}),
                    }
                },
            }
        },
        "/api/v1/Catalog/{id}": {
            "delete": {
                "tags": ["Catalog"],
                "parameters": [_int_param("id", "path", required=True)],
                "responses": dict([("204", {"description": "Success"}), _problem("404", "Not Found")]),
            }
        },
        "/api/v1/catalog/items/{catalogItemId}/pic": {
            "get": {
                "tags": ["Pic"],
                "parameters": [_int_param("catalogItemId", "path", required=True)],
                "responses": dict([_problem("404", "Not Found"), _problem("400", "Bad Request")]),
            }
        },
    }

    def _str_prop() -> dict[str, Any]:
        return {"type": "string", "nullable": True}

    def _int_prop() -> dict[str, Any]:
        return {"type": "integer", "format": "int32"}

    components = {
        "schemas": {
            "CatalogType": {
                "type": "object",
                "properties": {"id": _int_prop(), "type": _str_prop()},
                "nullable": True,
            },
            "CatalogBrand": {
                "type": "object",
                "properties": {"id": _int_prop(), "brand": _str_prop()},
                "nullable": True,
            },
            "CatalogItem": {
                "type": "object",
                "properties": {
                    "id": _int_prop(),
                    "name": _str_prop(),
                    "description": _str_prop(),
                    "price": {"type": "number", "format": "double"},
                    "pictureFileName": _str_prop(),
                    "pictureUri": _str_prop(),
                    "catalogTypeId": _int_prop(),
                    "catalogType": _ref("CatalogType"),
                    "catalogBrandId": _int_prop(),
                    "catalogBrand": _ref("CatalogBrand"),
                    "availableStock": _int_prop(),
                    "restockThreshold": _int_prop(),
                    "maxStockThreshold": _int_prop(),
                    "onReorder": {"type": "boolean"},
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
            "CatalogItemPaginatedItemsViewModel": {
                "type": "object",
                "properties": {
                    "pageIndex": {"type": "integer", "format": "int32", "readOnly": True},
                    "pageSize": {"type": "integer", "format": "int32", "readOnly": True},
                    "count": {"type": "integer", "format": "int64", "readOnly": True},
                    "data": {
                        "type": "array",
                        "items": _ref("CatalogItem"),
                        "nullable": True,
                        "readOnly": True,
                    },
                },
                "nullable": True,
            },
        }
    }

    return {
        "openapi": "3.0.1",
        "info": {
            "title": "eShopOnContainers - Catalog HTTP API",
            "description": "The Catalog Microservice HTTP API. This is a Data-Driven/CRUD microservice sample",
            "version": "v1",
        },
        "paths": paths,
        "components": components,
    }
