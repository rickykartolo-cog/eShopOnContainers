"""MongoDB repository preserving the .NET ``LocationsRepository`` queries:
unchanged collection names (``Locations``, ``UserLocation``), BSON field names,
and the combined ``$near`` (distance ordering) + ``$geoIntersects`` region query
against the ``Location`` 2dsphere index."""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from locations_api.models import (
    Location,
    UserLocation,
    location_from_bson,
    user_location_from_bson,
    user_location_to_bson,
)


class LocationsRepository:
    def __init__(self, database: AsyncIOMotorDatabase) -> None:
        self._database = database
        self._locations = database.get_collection("Locations")
        self._user_locations = database.get_collection("UserLocation")

    @classmethod
    def from_connection_string(cls, connection_string: str, database: str) -> LocationsRepository:
        client: AsyncIOMotorClient = AsyncIOMotorClient(connection_string, tz_aware=True)
        return cls(client[database])

    @property
    def database(self) -> AsyncIOMotorDatabase:
        return self._database

    async def get(self, location_id: int) -> Location | None:
        document = await self._locations.find_one({"LocationId": location_id})
        return location_from_bson(document) if document else None

    async def get_user_location(self, user_id: str) -> UserLocation | None:
        document = await self._user_locations.find_one({"UserId": user_id})
        return user_location_from_bson(document) if document else None

    async def get_location_list(self) -> list[Location]:
        documents = await self._locations.find({}).to_list(length=None)
        return [location_from_bson(document) for document in documents]

    async def get_current_user_regions_list(self, longitude: float, latitude: float) -> list[Location]:
        point = {"type": "Point", "coordinates": [longitude, latitude]}
        # Same rendered filter as the .NET driver's Builders.Filter.And(Near, GeoIntersects):
        # $near orders results by distance from the user's position.
        query = {
            "Location": {"$near": {"$geometry": point}},
            "Polygon": {"$geoIntersects": {"$geometry": point}},
        }
        documents = await self._locations.find(query).to_list(length=None)
        return [location_from_bson(document) for document in documents]

    async def add_user_location(self, user_location: UserLocation) -> None:
        await self._user_locations.insert_one(user_location_to_bson(user_location))

    async def update_user_location(self, user_location: UserLocation) -> None:
        await self._user_locations.replace_one(
            {"UserId": user_location.user_id},
            user_location_to_bson(user_location),
            upsert=True,
        )
