"""HTTP response serialization matching ASP.NET Core 3.1 + AddNewtonsoftJson:
camelCase property names, decimals preserving scale, UTF-8 JSON."""

from __future__ import annotations

from typing import Any

from eshop_common.events import dumps_newtonsoft
from fastapi import Response

from catalog_api.models import CatalogBrand, CatalogItem, CatalogType


def item_payload(item: CatalogItem, picture_uri: str | None) -> dict[str, Any]:
    """CamelCase ``CatalogItem`` shape, field-for-field with the .NET model."""
    brand = getattr(item, "CatalogBrand_", None)
    ctype = getattr(item, "CatalogType_", None)
    return {
        "id": item.Id,
        "name": item.Name,
        "description": item.Description,
        "price": item.Price,
        "pictureFileName": item.PictureFileName,
        "pictureUri": picture_uri,
        "catalogTypeId": item.CatalogTypeId,
        "catalogType": type_payload(ctype) if ctype is not None else None,
        "catalogBrandId": item.CatalogBrandId,
        "catalogBrand": brand_payload(brand) if brand is not None else None,
        "availableStock": item.AvailableStock,
        "restockThreshold": item.RestockThreshold,
        "maxStockThreshold": item.MaxStockThreshold,
        "onReorder": item.OnReorder,
    }


def brand_payload(brand: CatalogBrand) -> dict[str, Any]:
    return {"id": brand.Id, "brand": brand.Brand}


def type_payload(ctype: CatalogType) -> dict[str, Any]:
    return {"id": ctype.Id, "type": ctype.Type}


def paginated_payload(page_index: int, page_size: int, count: int, data: list[dict[str, Any]]) -> dict[str, Any]:
    """``PaginatedItemsViewModel<CatalogItem>`` shape: pageIndex, pageSize, count, data."""
    return {"pageIndex": page_index, "pageSize": page_size, "count": count, "data": data}


def json_response(payload: Any, status_code: int = 200) -> Response:
    return Response(
        content=dumps_newtonsoft(payload),
        status_code=status_code,
        media_type="application/json; charset=utf-8",
    )


def fill_product_url(item: CatalogItem, pic_base_url: str, azure_storage_enabled: bool) -> str | None:
    """Port of ``CatalogItemExtensions.FillProductUrl``."""
    if azure_storage_enabled:
        return pic_base_url + (item.PictureFileName or "")
    return pic_base_url.replace("[0]", str(item.Id))
