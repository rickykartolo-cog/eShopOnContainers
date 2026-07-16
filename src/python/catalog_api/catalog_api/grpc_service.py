"""gRPC Catalog service, port of ``CatalogService`` (Grpc/CatalogService.cs)
against the unchanged ``catalog.proto``:

- ``GetItemById``: id <= 0 → FAILED_PRECONDITION, missing → NOT_FOUND.
- ``GetItemsByIds``: comma-separated ids (invalid → NOT_FOUND with the exact
  .NET detail message) or name-ordered pagination; field-for-field responses.
"""

from __future__ import annotations

import grpc
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from catalog_api.grpc_gen import catalog_pb2, catalog_pb2_grpc
from catalog_api.models import CatalogItem
from catalog_api.serialization import fill_product_url
from catalog_api.settings import CatalogSettings


def _item_query():
    # No Include() in the .NET queries: CatalogBrand/CatalogType stay null, so the
    # catalog_brand/catalog_type submessages are never populated in responses.
    return select(CatalogItem)


class CatalogGrpcService(catalog_pb2_grpc.CatalogServicer):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: CatalogSettings) -> None:
        self._session_factory = session_factory
        self._settings = settings

    def _map_item(self, item: CatalogItem) -> catalog_pb2.CatalogItemResponse:
        response = catalog_pb2.CatalogItemResponse(
            id=item.Id,
            name=item.Name or "",
            description=item.Description or "",
            price=float(item.Price),
            picture_file_name=item.PictureFileName or "",
            picture_uri=fill_product_url(item, self._settings.pic_base_url, self._settings.azure_storage_enabled)
            or "",
            available_stock=item.AvailableStock,
            restock_threshold=item.RestockThreshold,
            max_stock_threshold=item.MaxStockThreshold,
            on_reorder=item.OnReorder,
        )
        return response

    async def GetItemById(self, request, context):  # noqa: N802 (proto naming)
        if request.id <= 0:
            context.set_code(grpc.StatusCode.FAILED_PRECONDITION)
            context.set_details(f"Id must be > 0 (received {request.id})")
            return catalog_pb2.CatalogItemResponse()
        async with self._session_factory() as session:
            item = (
                await session.execute(_item_query().where(CatalogItem.Id == request.id))
            ).scalar_one_or_none()
        if item is None:
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Product with id {request.id} do not exist")
            return catalog_pb2.CatalogItemResponse()
        return self._map_item(item)

    async def GetItemsByIds(self, request, context):  # noqa: N802 (proto naming)
        page_size = request.pageSize
        page_index = request.pageIndex
        async with self._session_factory() as session:
            if request.ids:
                items = await self._items_by_ids(session, request.ids)
                if not items:
                    context.set_code(grpc.StatusCode.NOT_FOUND)
                    context.set_details("ids value invalid. Must be comma-separated list of numbers")
                    return catalog_pb2.PaginatedItemsResponse(pageIndex=1, pageSize=0, count=0)
                return catalog_pb2.PaginatedItemsResponse(
                    pageIndex=1, pageSize=len(items), count=len(items),
                    data=[self._map_item(item) for item in items],
                )
            total = (await session.execute(select(func.count()).select_from(CatalogItem))).scalar_one()
            rows = (
                await session.execute(
                    _item_query().order_by(CatalogItem.Name).offset(page_size * page_index).limit(page_size)
                )
            ).scalars().all()
        return catalog_pb2.PaginatedItemsResponse(
            pageIndex=page_index, pageSize=page_size, count=total,
            data=[self._map_item(item) for item in rows],
        )

    async def _items_by_ids(self, session: AsyncSession, ids: str) -> list[CatalogItem]:
        parsed: list[int] = []
        for chunk in ids.split(","):
            try:
                parsed.append(int(chunk))
            except ValueError:
                return []
        rows = (await session.execute(_item_query().where(CatalogItem.Id.in_(parsed)))).scalars().all()
        return list(rows)


def create_grpc_server(
    session_factory: async_sessionmaker[AsyncSession], settings: CatalogSettings
) -> grpc.aio.Server:
    server = grpc.aio.server()
    catalog_pb2_grpc.add_CatalogServicer_to_server(CatalogGrpcService(session_factory, settings), server)
    return server
