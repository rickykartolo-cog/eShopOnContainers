"""HTTP routes preserving Catalog.API's frozen contract (master prompt §4.1).

Semantics ported from ``CatalogController``/``PicController``, including ASP.NET
routing behavior: int route-constraint mismatches produce 404, model-binding
failures produce the customized 400 ``ValidationProblemDetails``, string results
are text/plain, and empty results (``NotFound()``/``BadRequest()``/``NoContent()``)
have empty bodies.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from catalog_api.events import ProductPriceChangedIntegrationEvent
from catalog_api.integration import CatalogIntegrationEventService
from catalog_api.models import CatalogBrand, CatalogItem, CatalogType, catalog_hilo
from catalog_api.serialization import (
    brand_payload,
    fill_product_url,
    item_payload,
    json_response,
    paginated_payload,
    type_payload,
)
from catalog_api.settings import CatalogSettings

MIME_TYPES = {
    ".png": "image/png",
    ".gif": "image/gif",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".wmf": "image/wmf",
    ".jp2": "image/jp2",
    ".svg": "image/svg+xml",
}

router = APIRouter()


def _query_int(request: Request, name: str, default: int) -> int | Response:
    """Case-insensitive query binding like ASP.NET; invalid values produce the
    customized 400 ``ValidationProblemDetails``."""
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


def _validation_problem(request: Request, errors: dict[str, list[str]]) -> Response:
    payload: dict[str, Any] = {
        "type": "https://tools.ietf.org/html/rfc7231#section-6.5.1",
        "title": "One or more validation errors occurred.",
        "status": 400,
        "detail": "Please refer to the errors property for additional details.",
        "instance": request.url.path,
        "errors": errors,
    }
    from eshop_common.events import dumps_newtonsoft

    return Response(content=dumps_newtonsoft(payload), status_code=400, media_type="application/problem+json")


def _session(request: Request) -> AsyncSession:
    return request.state.session


def _settings(request: Request) -> CatalogSettings:
    return request.app.state.catalog_settings


def _fill(items: list[CatalogItem], settings: CatalogSettings) -> list[dict[str, Any]]:
    return [
        item_payload(item, fill_product_url(item, settings.pic_base_url, settings.azure_storage_enabled))
        for item in items
    ]


@router.get("/", include_in_schema=False)
async def home(request: Request) -> Response:
    return RedirectResponse(url=f"{request.scope.get('root_path', '')}/swagger")


@router.get("/_proto/", include_in_schema=False)
async def proto(request: Request) -> Response:
    proto_path = request.app.state.proto_path
    return PlainTextResponse(proto_path.read_text(encoding="utf-8"))


@router.get("/api/v1/catalog/items")
async def items(request: Request) -> Response:
    session, settings = _session(request), _settings(request)
    ids = None
    for key, value in request.query_params.items():
        if key.lower() == "ids":
            ids = value
    page_size = _query_int(request, "pageSize", 10)
    if isinstance(page_size, Response):
        return page_size
    page_index = _query_int(request, "pageIndex", 0)
    if isinstance(page_index, Response):
        return page_index

    if ids:
        found = await _items_by_ids(session, ids)
        if not found:
            return PlainTextResponse("ids value invalid. Must be comma-separated list of numbers", status_code=400)
        return json_response(_fill(found, settings))

    total = (await session.execute(select(func.count()).select_from(CatalogItem))).scalar_one()
    rows = (
        await session.execute(
            select(CatalogItem).order_by(CatalogItem.Name).offset(page_size * page_index).limit(page_size)
        )
    ).scalars().all()
    return json_response(paginated_payload(page_index, page_size, total, _fill(list(rows), settings)))


async def _items_by_ids(session: AsyncSession, ids: str) -> list[CatalogItem]:
    parsed: list[int] = []
    for chunk in ids.split(","):
        try:
            parsed.append(int(chunk))
        except ValueError:
            return []
    rows = (await session.execute(select(CatalogItem).where(CatalogItem.Id.in_(parsed)))).scalars().all()
    return list(rows)


@router.get("/api/v1/catalog/items/withname/{name}")
async def items_with_name(request: Request, name: str) -> Response:
    session, settings = _session(request), _settings(request)
    page_size = _query_int(request, "pageSize", 10)
    if isinstance(page_size, Response):
        return page_size
    page_index = _query_int(request, "pageIndex", 0)
    if isinstance(page_index, Response):
        return page_index

    condition = CatalogItem.Name.startswith(name, autoescape=True)
    total = (await session.execute(select(func.count()).select_from(CatalogItem).where(condition))).scalar_one()
    rows = (
        await session.execute(select(CatalogItem).where(condition).offset(page_size * page_index).limit(page_size))
    ).scalars().all()
    return json_response(paginated_payload(page_index, page_size, total, _fill(list(rows), settings)))


@router.get("/api/v1/catalog/items/type/all/brand")
@router.get("/api/v1/catalog/items/type/all/brand/{catalog_brand_id}")
async def items_by_brand(request: Request, catalog_brand_id: str | None = None) -> Response:
    brand_id: int | None = None
    if catalog_brand_id is not None:
        try:
            brand_id = int(catalog_brand_id)
        except ValueError:
            return Response(status_code=404)  # {catalogBrandId:int?} constraint mismatch
    return await _filtered_items(request, None, brand_id)


@router.get("/api/v1/catalog/items/type/{catalog_type_id}/brand")
@router.get("/api/v1/catalog/items/type/{catalog_type_id}/brand/{catalog_brand_id}")
async def items_by_type_and_brand(
    request: Request, catalog_type_id: str, catalog_brand_id: str | None = None
) -> Response:
    try:
        type_id = int(catalog_type_id)
    except ValueError:
        return _validation_problem(
            request, {"catalogTypeId": [f"The value '{catalog_type_id}' is not valid."]}
        )
    brand_id: int | None = None
    if catalog_brand_id is not None:
        try:
            brand_id = int(catalog_brand_id)
        except ValueError:
            return Response(status_code=404)  # {catalogBrandId:int?} constraint mismatch
    return await _filtered_items(request, type_id, brand_id)


async def _filtered_items(request: Request, type_id: int | None, brand_id: int | None) -> Response:
    session, settings = _session(request), _settings(request)
    page_size = _query_int(request, "pageSize", 10)
    if isinstance(page_size, Response):
        return page_size
    page_index = _query_int(request, "pageIndex", 0)
    if isinstance(page_index, Response):
        return page_index

    query = select(CatalogItem)
    count_query = select(func.count()).select_from(CatalogItem)
    if type_id is not None:
        query = query.where(CatalogItem.CatalogTypeId == type_id)
        count_query = count_query.where(CatalogItem.CatalogTypeId == type_id)
    if brand_id is not None:
        query = query.where(CatalogItem.CatalogBrandId == brand_id)
        count_query = count_query.where(CatalogItem.CatalogBrandId == brand_id)

    total = (await session.execute(count_query)).scalar_one()
    rows = (await session.execute(query.offset(page_size * page_index).limit(page_size))).scalars().all()
    return json_response(paginated_payload(page_index, page_size, total, _fill(list(rows), settings)))


@router.get("/api/v1/catalog/items/{item_id}")
async def item_by_id(request: Request, item_id: str) -> Response:
    try:
        parsed = int(item_id)
    except ValueError:
        return Response(status_code=404)  # {id:int} constraint mismatch
    if parsed <= 0:
        return Response(status_code=400)

    session, settings = _session(request), _settings(request)
    item = (
        await session.execute(select(CatalogItem).where(CatalogItem.Id == parsed))
    ).scalar_one_or_none()
    if item is None:
        return Response(status_code=404)
    return json_response(
        item_payload(item, fill_product_url(item, settings.pic_base_url, settings.azure_storage_enabled))
    )


# ASP.NET routing is case-insensitive; WebMVC requests the camelCase form
# (API.cs GetAllCatalogTypes/Brands), so both spellings must match. The alias
# is hidden from the schema to keep the frozen OpenAPI document unchanged.
@router.get("/api/v1/catalog/catalogtypes")
@router.get("/api/v1/catalog/catalogTypes", include_in_schema=False)
async def catalog_types(request: Request) -> Response:
    session = _session(request)
    rows = (await session.execute(select(CatalogType))).scalars().all()
    return json_response([type_payload(row) for row in rows])


@router.get("/api/v1/catalog/catalogbrands")
@router.get("/api/v1/catalog/catalogBrands", include_in_schema=False)
async def catalog_brands(request: Request) -> Response:
    session = _session(request)
    rows = (await session.execute(select(CatalogBrand))).scalars().all()
    return json_response([brand_payload(row) for row in rows])


async def _read_item_body(request: Request) -> dict[str, Any] | Response:
    import json

    try:
        body = json.loads(await request.body(), parse_float=Decimal)
    except (ValueError, UnicodeDecodeError):
        return _validation_problem(request, {"": ["The input was not valid."]})
    if not isinstance(body, dict):
        return _validation_problem(request, {"": ["The input was not valid."]})
    return {key.lower(): value for key, value in body.items()}


def _created_at_item(request: Request, item_id: int) -> Response:
    base = str(request.base_url).rstrip("/")
    root_path = request.scope.get("root_path", "")
    return Response(status_code=201, headers={"Location": f"{base}{root_path}/api/v1/Catalog/items/{item_id}"})


@router.put("/api/v1/catalog/items")
async def update_product(request: Request) -> Response:
    body = await _read_item_body(request)
    if isinstance(body, Response):
        return body
    session = _session(request)
    try:
        product_id = int(body.get("id", 0))
        new_price = Decimal(str(body.get("price", 0)))
    except (ValueError, InvalidOperation):
        return _validation_problem(request, {"": ["The input was not valid."]})

    item = (
        await session.execute(select(CatalogItem).where(CatalogItem.Id == product_id))
    ).scalar_one_or_none()
    if item is None:
        return json_response({"message": f"Item with id {product_id} not found."}, status_code=404)

    old_price = item.Price
    raise_price_changed = old_price != new_price

    item.Name = body.get("name", item.Name)
    item.Description = body.get("description")
    item.Price = new_price
    item.PictureFileName = body.get("picturefilename")
    item.CatalogTypeId = int(body.get("catalogtypeid", item.CatalogTypeId))
    item.CatalogBrandId = int(body.get("catalogbrandid", item.CatalogBrandId))
    item.AvailableStock = int(body.get("availablestock", 0))
    item.RestockThreshold = int(body.get("restockthreshold", 0))
    item.MaxStockThreshold = int(body.get("maxstockthreshold", 0))
    item.OnReorder = bool(body.get("onreorder", False))

    if raise_price_changed:
        event = ProductPriceChangedIntegrationEvent(
            ProductId=item.Id, NewPrice=new_price, OldPrice=old_price
        )
        integration: CatalogIntegrationEventService = request.state.integration_service
        await integration.save_event_and_catalog_context_changes(event)
        await integration.publish_through_event_bus(event)
    else:
        await session.commit()

    return _created_at_item(request, product_id)


@router.post("/api/v1/catalog/items")
async def create_product(request: Request) -> Response:
    body = await _read_item_body(request)
    if isinstance(body, Response):
        return body
    session = _session(request)
    try:
        item = CatalogItem(
            Id=await catalog_hilo.next_id(session),
            CatalogBrandId=int(body.get("catalogbrandid", 0)),
            CatalogTypeId=int(body.get("catalogtypeid", 0)),
            Description=body.get("description"),
            Name=body.get("name") or "",
            PictureFileName=body.get("picturefilename"),
            Price=Decimal(str(body.get("price", 0))),
            AvailableStock=0,
            RestockThreshold=0,
            MaxStockThreshold=0,
            OnReorder=False,
        )
    except (ValueError, InvalidOperation):
        return _validation_problem(request, {"": ["The input was not valid."]})
    session.add(item)
    await session.commit()
    return _created_at_item(request, item.Id)


@router.delete("/api/v1/catalog/{item_id}")
async def delete_product(request: Request, item_id: str) -> Response:
    try:
        parsed = int(item_id)
    except ValueError:
        # `{id}` has no route constraint: binding failure produces the 400 problem body.
        return _validation_problem(request, {"id": [f"The value '{item_id}' is not valid."]})
    session = _session(request)
    item = (
        await session.execute(select(CatalogItem).where(CatalogItem.Id == parsed))
    ).scalar_one_or_none()
    if item is None:
        return Response(status_code=404)
    await session.execute(sa_delete(CatalogItem).where(CatalogItem.Id == parsed))
    await session.commit()
    return Response(status_code=204)


# ASP.NET ignores trailing slashes and the PicBaseUrl clients use ".../pic/";
# serve it directly rather than letting FastAPI 307-redirect to the internal
# container hostname, which is unreachable from behind the gateway.
@router.get("/api/v1/catalog/items/{catalog_item_id}/pic")
@router.get("/api/v1/catalog/items/{catalog_item_id}/pic/", include_in_schema=False)
async def get_image(request: Request, catalog_item_id: str) -> Response:
    try:
        parsed = int(catalog_item_id)
    except ValueError:
        return Response(status_code=404)  # {catalogItemId:int} constraint mismatch
    if parsed <= 0:
        return Response(status_code=400)

    session, settings = _session(request), _settings(request)
    item = (
        await session.execute(select(CatalogItem).where(CatalogItem.Id == parsed))
    ).scalar_one_or_none()
    if item is None:
        return Response(status_code=404)

    path = settings.pics_path / (item.PictureFileName or "")
    extension = path.suffix.lower()
    mimetype = MIME_TYPES.get(extension, "application/octet-stream")
    buffer = path.read_bytes()  # missing file -> unhandled -> 500, like the .NET filter
    return Response(content=buffer, media_type=mimetype)

