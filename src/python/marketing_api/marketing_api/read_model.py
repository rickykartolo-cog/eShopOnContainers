"""Mongo read/personalization model: the ``MarketingReadDataModel`` collection
with the unchanged BSON element names used by the .NET MongoDB driver
(``_id`` ObjectId, ``UserId``, ``Locations`` [{``LocationId``, ``Code``,
``Description``}], ``UpdateDate``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

COLLECTION_NAME = "MarketingReadDataModel"


@dataclass
class Location:
    LocationId: int
    Code: str | None = None
    Description: str | None = None

    def to_bson(self) -> dict[str, Any]:
        return {"LocationId": self.LocationId, "Code": self.Code, "Description": self.Description}

    @classmethod
    def from_bson(cls, document: dict[str, Any]) -> Location:
        return cls(
            LocationId=int(document.get("LocationId", 0)),
            Code=document.get("Code"),
            Description=document.get("Description"),
        )


@dataclass
class MarketingData:
    UserId: str
    Locations: list[Location] = field(default_factory=list)
    UpdateDate: datetime | None = None
    Id: str | None = None

    @classmethod
    def from_bson(cls, document: dict[str, Any]) -> MarketingData:
        return cls(
            UserId=document.get("UserId", ""),
            Locations=[Location.from_bson(item) for item in document.get("Locations") or []],
            UpdateDate=document.get("UpdateDate"),
            Id=str(document["_id"]) if "_id" in document else None,
        )


class MarketingDataRepository:
    """Port of ``MarketingDataRepository``: ``GetAsync(userId)`` and the upserting
    ``UpdateLocationAsync`` (``$set Locations`` + ``$currentDate UpdateDate``)."""

    def __init__(self, database) -> None:
        self._collection = database[COLLECTION_NAME]

    async def get(self, user_id: str) -> MarketingData | None:
        document = await self._collection.find_one({"UserId": user_id})
        return MarketingData.from_bson(document) if document is not None else None

    async def update_location(self, marketing_data: MarketingData) -> None:
        await self._collection.update_one(
            {"UserId": marketing_data.UserId},
            {
                "$set": {"Locations": [location.to_bson() for location in marketing_data.Locations]},
                "$currentDate": {"UpdateDate": True},
            },
            upsert=True,
        )
