"""Mongo parity (master prompt §6.4) against a real MongoDB: seeded schema and
indexes match the frozen dump, the real ``$near``/``$geoIntersects`` query
reproduces the .NET functional-test oracles, and documents written by either
implementation are readable by the other (bidirectional round-trip)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from bson import ObjectId
from eshop_common.testing import mongo_url
from motor.motor_asyncio import AsyncIOMotorClient

from locations_api.models import UserLocation, user_location_from_bson, user_location_to_bson
from locations_api.repository import LocationsRepository
from locations_api.seed import seed

pytestmark = pytest.mark.integration


@pytest.fixture
async def repository():
    client: AsyncIOMotorClient = AsyncIOMotorClient(mongo_url(), tz_aware=True)
    database_name = f"LocationsDbTest{uuid.uuid4().hex[:8]}"
    repo = LocationsRepository(client[database_name])
    await seed(repo)
    yield repo
    await client.drop_database(database_name)
    client.close()


async def test_seeded_schema_matches_frozen_dump(repository):
    """Same field names/BSON types and the Location_2dsphere index as
    contracts/db/locationsdb.mongoschema.txt."""
    database = repository.database
    indexes = await database.get_collection("Locations").index_information()
    assert "_id_" in indexes
    assert indexes["Location_2dsphere"]["key"] == [("Location", "2dsphere")]

    document = await database.get_collection("Locations").find_one({"Code": "NA"})
    assert set(document.keys()) == {
        "_id", "LocationId", "Code", "Parent_Id", "Description",
        "Latitude", "Longitude", "Location", "Polygon",
    }
    assert isinstance(document["_id"], ObjectId)
    assert isinstance(document["LocationId"], int)
    assert isinstance(document["Latitude"], float)
    assert document["Parent_Id"] is None
    assert document["Location"]["type"] == "Point"
    assert document["Polygon"]["type"] == "Polygon"

    child = await database.get_collection("Locations").find_one({"Code": "US"})
    assert isinstance(child["Parent_Id"], ObjectId)
    assert child["Parent_Id"] == document["_id"]

    assert await database.get_collection("Locations").count_documents({}) == 11


@pytest.mark.parametrize(
    ("longitude", "latitude", "expected_codes"),
    [
        (-122.315752, 47.604610, ["SEAT", "WHT", "NA", "US"]),
        (-122.119998, 47.690876, ["REDM", "WHT", "NA", "US"]),
        (-121.040360, 48.091631, ["WHT", "NA", "US"]),
    ],
)
async def test_near_geointersects_matches_dotnet_oracles(repository, longitude, latitude, expected_codes):
    regions = await repository.get_current_user_regions_list(longitude, latitude)
    assert [region.code for region in regions] == expected_codes


async def test_user_location_upsert_roundtrip(repository):
    user_id = "4611ce3f-380d-4db5-8d76-87a8689058ed"
    entity = UserLocation(user_id=user_id, location_id=4, update_date=datetime.now(UTC))
    await repository.update_user_location(entity)

    raw = await repository.database.get_collection("UserLocation").find_one({"UserId": user_id})
    # Exact BSON shape the .NET driver writes/reads: _id ObjectId, UserId string,
    # LocationId int32, UpdateDate BSON date.
    assert set(raw.keys()) == {"_id", "UserId", "LocationId", "UpdateDate"}
    assert isinstance(raw["_id"], ObjectId)
    assert raw["LocationId"] == 4
    assert isinstance(raw["UpdateDate"], datetime)

    # Upsert replaces (single document, stable _id), like ReplaceOneAsync IsUpsert.
    await repository.update_user_location(UserLocation(user_id=user_id, location_id=5))
    updated = await repository.database.get_collection("UserLocation").find_one({"UserId": user_id})
    assert updated["_id"] == raw["_id"]
    assert updated["LocationId"] == 5
    assert await repository.database.get_collection("UserLocation").count_documents({}) == 1


async def test_reads_document_written_by_dotnet_driver(repository):
    """Insert a document exactly as the .NET driver serializes UserLocation and
    read it back through the Python model."""
    dotnet_document = {
        "_id": ObjectId(),
        "UserId": "e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5",
        "LocationId": 4,
        "UpdateDate": datetime(2020, 1, 2, 3, 4, 5, 678000, tzinfo=UTC),
    }
    await repository.database.get_collection("UserLocation").insert_one(dict(dotnet_document))

    entity = await repository.get_user_location("e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5")
    assert entity is not None
    assert entity.id == str(dotnet_document["_id"])
    assert entity.location_id == 4
    assert entity.update_date == dotnet_document["UpdateDate"]

    # And the Python serializer round-trips to the identical BSON fields.
    rewritten = user_location_to_bson(user_location_from_bson(dotnet_document))
    assert rewritten == {key: value for key, value in dotnet_document.items() if key != "_id"}


async def test_locations_seed_readable_by_dotnet_field_names(repository):
    """Every seeded document keeps the exact PascalCase member names the .NET
    class map expects (no camelCase drift)."""
    async for document in repository.database.get_collection("Locations").find({}):
        for field in ("LocationId", "Code", "Description", "Latitude", "Longitude", "Location", "Polygon"):
            assert field in document
        assert document["Location"]["coordinates"][0] == document["Longitude"]
        assert document["Location"]["coordinates"][1] == document["Latitude"]
