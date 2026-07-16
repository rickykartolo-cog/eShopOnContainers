"""Consumer side-effect tests: ``UserLocationUpdatedIntegrationEvent`` handling,
Mongo document parity (collection name and BSON element casing unchanged from
the .NET MongoDB driver), upsert/replace semantics, and idempotent duplicate
delivery."""

import json
from datetime import datetime

from marketing_api.consumers import MarketingEventConsumers
from marketing_api.read_model import COLLECTION_NAME, Location, MarketingData

GOLDEN_BODY = (
    '{"UserId":"e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5",'
    '"LocationList":[{"LocationId":1,"Code":"SEAT","Description":"Seattle"}],'
    '"Id":"11111111-2222-3333-4444-555555555555",'
    '"CreationDate":"2020-01-02T03:04:05.678Z"}'
)
USER_ID = "e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5"


async def deliver(event_bus, body: str) -> None:
    await event_bus.deliver("UserLocationUpdatedIntegrationEvent", body.encode("utf-8"))


async def test_collection_name_is_unchanged():
    assert COLLECTION_NAME == "MarketingReadDataModel"


async def test_event_creates_document_with_dotnet_bson_shape(repository, event_bus, mongo_database):
    consumers = MarketingEventConsumers(repository, event_bus)
    await consumers.subscribe_all()
    await deliver(event_bus, GOLDEN_BODY)

    document = await mongo_database[COLLECTION_NAME].find_one({"UserId": USER_ID})
    assert document is not None
    assert set(document.keys()) == {"_id", "UserId", "Locations", "UpdateDate"}
    assert document["Locations"] == [{"LocationId": 1, "Code": "SEAT", "Description": "Seattle"}]
    assert isinstance(document["UpdateDate"], datetime)


async def test_event_replaces_existing_locations(repository, event_bus, mongo_database):
    await repository.update_location(
        MarketingData(UserId=USER_ID, Locations=[Location(LocationId=99, Code="OLD", Description="Old")])
    )
    consumers = MarketingEventConsumers(repository, event_bus)
    await consumers.subscribe_all()
    await deliver(event_bus, GOLDEN_BODY)

    document = await mongo_database[COLLECTION_NAME].find_one({"UserId": USER_ID})
    assert document["Locations"] == [{"LocationId": 1, "Code": "SEAT", "Description": "Seattle"}]
    assert await mongo_database[COLLECTION_NAME].count_documents({}) == 1


async def test_duplicate_delivery_is_idempotent(repository, event_bus, mongo_database):
    consumers = MarketingEventConsumers(repository, event_bus)
    await consumers.subscribe_all()
    await deliver(event_bus, GOLDEN_BODY)
    await deliver(event_bus, GOLDEN_BODY)

    assert await mongo_database[COLLECTION_NAME].count_documents({}) == 1
    document = await mongo_database[COLLECTION_NAME].find_one({"UserId": USER_ID})
    assert document["Locations"] == [{"LocationId": 1, "Code": "SEAT", "Description": "Seattle"}]


async def test_empty_location_list_clears_locations(repository, event_bus, mongo_database):
    consumers = MarketingEventConsumers(repository, event_bus)
    await consumers.subscribe_all()
    await deliver(event_bus, GOLDEN_BODY)

    body = json.loads(GOLDEN_BODY)
    body["LocationList"] = []
    await deliver(event_bus, json.dumps(body))

    document = await mongo_database[COLLECTION_NAME].find_one({"UserId": USER_ID})
    assert document["Locations"] == []


async def test_repository_get_roundtrip(repository):
    await repository.update_location(
        MarketingData(UserId="42", Locations=[Location(LocationId=7, Code="BCN", Description="Barcelona")])
    )
    data = await repository.get("42")
    assert data is not None
    assert data.UserId == "42"
    assert data.Id is not None
    assert isinstance(data.UpdateDate, datetime)
    assert [(loc.LocationId, loc.Code, loc.Description) for loc in data.Locations] == [(7, "BCN", "Barcelona")]
    assert await repository.get("missing") is None
