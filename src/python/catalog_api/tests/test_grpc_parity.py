"""gRPC parity tests against the unchanged catalog.proto: status codes,
details, and field-for-field responses (Grpc/CatalogService.cs oracle)."""

import grpc
from sqlalchemy import select

from catalog_api.grpc_gen import catalog_pb2
from catalog_api.grpc_service import CatalogGrpcService
from catalog_api.models import CatalogItem


class FakeContext:
    def __init__(self) -> None:
        self.code = grpc.StatusCode.OK
        self.details = ""

    def set_code(self, code) -> None:
        self.code = code

    def set_details(self, details) -> None:
        self.details = details


async def first_item(session_factory) -> CatalogItem:
    async with session_factory() as session:
        return (
            await session.execute(select(CatalogItem).order_by(CatalogItem.Id))
        ).scalars().first()


async def test_get_item_by_id_failed_precondition(seeded_session_factory, catalog_settings):
    service = CatalogGrpcService(seeded_session_factory, catalog_settings)
    context = FakeContext()
    await service.GetItemById(catalog_pb2.CatalogItemRequest(id=0), context)
    assert context.code == grpc.StatusCode.FAILED_PRECONDITION
    assert context.details == "Id must be > 0 (received 0)"


async def test_get_item_by_id_not_found(seeded_session_factory, catalog_settings):
    service = CatalogGrpcService(seeded_session_factory, catalog_settings)
    context = FakeContext()
    await service.GetItemById(catalog_pb2.CatalogItemRequest(id=999999), context)
    assert context.code == grpc.StatusCode.NOT_FOUND
    assert context.details == "Product with id 999999 do not exist"


async def test_get_item_by_id_field_parity(seeded_session_factory, catalog_settings):
    item = await first_item(seeded_session_factory)
    service = CatalogGrpcService(seeded_session_factory, catalog_settings)
    context = FakeContext()
    response = await service.GetItemById(catalog_pb2.CatalogItemRequest(id=item.Id), context)
    assert context.code == grpc.StatusCode.OK
    assert response.id == item.Id
    assert response.name == item.Name
    assert response.description == item.Description
    assert response.price == float(item.Price)
    assert response.picture_file_name == item.PictureFileName
    assert response.picture_uri == f"http://localhost:5101/api/v1/catalog/items/{item.Id}/pic/"
    assert response.available_stock == item.AvailableStock
    assert response.restock_threshold == item.RestockThreshold
    assert response.max_stock_threshold == item.MaxStockThreshold
    assert response.on_reorder == item.OnReorder
    # No Include() in the .NET query: submessages stay unset.
    assert not response.HasField("catalog_brand")
    assert not response.HasField("catalog_type")


async def test_get_items_by_ids(seeded_session_factory, catalog_settings):
    item = await first_item(seeded_session_factory)
    service = CatalogGrpcService(seeded_session_factory, catalog_settings)
    context = FakeContext()
    response = await service.GetItemsByIds(
        catalog_pb2.CatalogItemsRequest(ids=f"{item.Id}"), context
    )
    assert context.code == grpc.StatusCode.OK
    assert response.pageIndex == 1
    assert response.pageSize == 1
    assert response.count == 1
    assert response.data[0].id == item.Id


async def test_get_items_by_invalid_ids_not_found(seeded_session_factory, catalog_settings):
    service = CatalogGrpcService(seeded_session_factory, catalog_settings)
    context = FakeContext()
    await service.GetItemsByIds(catalog_pb2.CatalogItemsRequest(ids="one,two"), context)
    assert context.code == grpc.StatusCode.NOT_FOUND
    assert context.details == "ids value invalid. Must be comma-separated list of numbers"


async def test_get_items_paginated_ordered_by_name(seeded_session_factory, catalog_settings):
    service = CatalogGrpcService(seeded_session_factory, catalog_settings)
    context = FakeContext()
    response = await service.GetItemsByIds(
        catalog_pb2.CatalogItemsRequest(pageSize=4, pageIndex=1), context
    )
    assert context.code == grpc.StatusCode.OK
    assert response.pageIndex == 1
    assert response.pageSize == 4
    assert response.count == 12
    assert len(response.data) == 4
    names = [item.name for item in response.data]
    assert names == sorted(names)
