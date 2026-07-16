"""HTTP functional tests: ports of ``Catalog.FunctionalTests/CatalogScenarios``
plus the §4.1 route-semantics table (pagination shape, status codes, picture
URI behavior, CreatedAtAction, price-change event gating)."""

import json

from eshop_common.outbox import EventState, IntegrationEventLogEntry
from sqlalchemy import func, select

from catalog_api.models import CatalogItem


async def get_first_item(client):
    response = await client.get("/api/v1/catalog/items?pageSize=1&pageIndex=0")
    return response.json()["data"][0]


async def test_get_all_catalogitems_ok(client):
    response = await client.get("/api/v1/catalog/items")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"pageIndex", "pageSize", "count", "data"}
    assert body["pageIndex"] == 0
    assert body["pageSize"] == 10
    assert body["count"] == 12
    assert len(body["data"]) == 10
    names = [item["name"] for item in body["data"]]
    assert names == sorted(names, key=str.lower)


async def test_item_shape_and_picture_uri(client):
    item = await get_first_item(client)
    assert list(item.keys()) == [
        "id", "name", "description", "price", "pictureFileName", "pictureUri",
        "catalogTypeId", "catalogType", "catalogBrandId", "catalogBrand",
        "availableStock", "restockThreshold", "maxStockThreshold", "onReorder",
    ]
    assert item["pictureUri"] == f"http://localhost:5101/api/v1/catalog/items/{item['id']}/pic/"
    assert item["catalogType"] is None and item["catalogBrand"] is None


async def test_paginated_items(client):
    response = await client.get("/api/v1/catalog/items?pageSize=2&pageIndex=1")
    body = response.json()
    assert body["pageIndex"] == 1 and body["pageSize"] == 2
    assert body["count"] == 12 and len(body["data"]) == 2


async def test_items_by_ids(client):
    first = await get_first_item(client)
    response = await client.get(f"/api/v1/catalog/items?ids={first['id']}")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list) and body[0]["id"] == first["id"]


async def test_items_by_invalid_ids_returns_bad_request_text(client):
    response = await client.get("/api/v1/catalog/items?ids=one,two")
    assert response.status_code == 400
    assert response.text == "ids value invalid. Must be comma-separated list of numbers"
    assert response.headers["content-type"].startswith("text/plain")


async def test_item_by_id_ok(client):
    first = await get_first_item(client)
    response = await client.get(f"/api/v1/catalog/items/{first['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == first["id"]


async def test_item_by_nonpositive_id_bad_request(client):
    response = await client.get("/api/v1/catalog/items/0")
    assert response.status_code == 400
    assert response.content == b""


async def test_item_by_missing_id_not_found(client):
    response = await client.get("/api/v1/catalog/items/999999")
    assert response.status_code == 404
    assert response.content == b""


async def test_item_by_noninteger_id_route_mismatch_404(client):
    # {id:int} route constraint: non-numeric segment does not match any route.
    response = await client.get("/api/v1/catalog/items/notanumber")
    assert response.status_code == 404


async def test_items_withname(client):
    response = await client.get("/api/v1/catalog/items/withname/.NET?pageSize=5&pageIndex=0")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 5
    assert all(item["name"].startswith(".NET") for item in body["data"])


async def test_items_by_type_and_brand(client):
    response = await client.get("/api/v1/catalog/items/type/2/brand/2")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 3
    assert all(i["catalogTypeId"] == 2 and i["catalogBrandId"] == 2 for i in body["data"])


async def test_items_by_type_all_brands(client):
    response = await client.get("/api/v1/catalog/items/type/2/brand")
    assert response.json()["count"] == 7


async def test_items_by_brand_only(client):
    response = await client.get("/api/v1/catalog/items/type/all/brand/2")
    assert response.json()["count"] == 6


async def test_items_all_types_all_brands(client):
    response = await client.get("/api/v1/catalog/items/type/all/brand")
    assert response.json()["count"] == 12


async def test_catalogtypes_shape(client):
    response = await client.get("/api/v1/catalog/catalogtypes")
    assert response.status_code == 200
    body = response.json()
    assert [t["type"] for t in body] == ["Mug", "T-Shirt", "Sheet", "USB Memory Stick"]
    assert all(set(t.keys()) == {"id", "type"} for t in body)


async def test_catalogbrands_shape(client):
    response = await client.get("/api/v1/catalog/catalogbrands")
    assert response.status_code == 200
    body = response.json()
    assert [b["brand"] for b in body] == ["Azure", ".NET", "Visual Studio", "SQL Server", "Other"]
    assert all(set(b.keys()) == {"id", "brand"} for b in body)


async def test_routing_is_case_insensitive(client):
    response = await client.get("/api/v1/Catalog/items")
    assert response.status_code == 200


async def test_create_item_returns_201_created_at_action(client, seeded_session_factory):
    payload = {
        "name": "New Item", "description": "desc", "price": 10.5,
        "pictureFileName": "1.png", "catalogTypeId": 1, "catalogBrandId": 2,
    }
    response = await client.post("/api/v1/catalog/items", json=payload)
    assert response.status_code == 201
    assert response.content == b""
    location = response.headers["location"]
    assert "/api/v1/Catalog/items/" in location
    new_id = int(location.rsplit("/", 1)[1])
    async with seeded_session_factory() as session:
        item = (await session.execute(select(CatalogItem).where(CatalogItem.Id == new_id))).scalar_one()
        assert item.AvailableStock == 0 and item.Name == "New Item"


async def test_update_missing_item_404_with_message(client):
    payload = {"id": 999999, "name": "x", "price": 1, "catalogTypeId": 1, "catalogBrandId": 1}
    response = await client.put("/api/v1/catalog/items", json=payload)
    assert response.status_code == 404
    assert response.json() == {"message": "Item with id 999999 not found."}


async def test_update_price_change_publishes_event_through_outbox(client, seeded_session_factory, event_bus):
    first = await get_first_item(client)
    first["price"] = 999.99
    response = await client.put("/api/v1/catalog/items", json=first)
    assert response.status_code == 201

    assert len(event_bus.published) == 1
    event = event_bus.published[0]
    assert type(event).event_name() == "ProductPriceChangedIntegrationEvent"
    body = json.loads(event.to_json())
    assert body["ProductId"] == first["id"] and body["NewPrice"] == 999.99

    async with seeded_session_factory() as session:
        entry = (
            await session.execute(
                select(IntegrationEventLogEntry).where(IntegrationEventLogEntry.EventId == event.id)
            )
        ).scalar_one()
        assert entry.State == int(EventState.Published)


async def test_update_without_price_change_publishes_nothing(client, event_bus):
    first = await get_first_item(client)
    first["description"] = "updated description"
    response = await client.put("/api/v1/catalog/items", json=first)
    assert response.status_code == 201
    assert event_bus.published == []


async def test_delete_item_204_then_404(client, seeded_session_factory):
    first = await get_first_item(client)
    response = await client.delete(f"/api/v1/catalog/{first['id']}")
    assert response.status_code == 204
    assert response.content == b""
    response = await client.delete(f"/api/v1/catalog/{first['id']}")
    assert response.status_code == 404
    async with seeded_session_factory() as session:
        remaining = (await session.execute(select(func.count()).select_from(CatalogItem))).scalar_one()
        assert remaining == 11


async def test_pic_bad_request_and_not_found(client):
    assert (await client.get("/api/v1/catalog/items/0/pic")).status_code == 400
    assert (await client.get("/api/v1/catalog/items/999999/pic")).status_code == 404


async def test_pic_serves_png(client, tmp_path, app):
    app.state.catalog_settings.settings._values["pics_path"] = str(tmp_path)
    first = await get_first_item(client)
    (tmp_path / first["pictureFileName"]).write_bytes(b"\x89PNG fake")
    response = await client.get(f"/api/v1/catalog/items/{first['id']}/pic")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content == b"\x89PNG fake"
