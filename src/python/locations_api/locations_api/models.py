"""Domain models mirroring the .NET ``Locations``/``UserLocation`` documents.

BSON documents keep the exact field names written by the MongoDB .NET driver
(PascalCase members, ``_id`` ObjectId, ``Parent_Id`` ObjectId). HTTP payloads
use the camelCase names produced by ASP.NET Core 3.1 + AddNewtonsoftJson
(``parent_Id`` for the ``Parent_Id`` member).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId


@dataclass
class LocationPoint:
    coordinates: list[float] = field(default_factory=list)
    type: str = "Point"

    @classmethod
    def of(cls, longitude: float, latitude: float) -> LocationPoint:
        return cls(coordinates=[longitude, latitude])


@dataclass
class LocationPolygon:
    coordinates: list[list[list[float]]] = field(default_factory=list)
    type: str = "Polygon"

    @classmethod
    def of(cls, coordinates_list: list[tuple[float, float]]) -> LocationPolygon:
        return cls(coordinates=[[[lon, lat] for lon, lat in coordinates_list]])


@dataclass
class Location:
    id: str | None = None
    location_id: int = 0
    code: str | None = None
    parent_id: str | None = None
    description: str | None = None
    latitude: float = 0.0
    longitude: float = 0.0
    location: LocationPoint | None = None
    polygon: LocationPolygon | None = None

    def set_location(self, lon: float, lat: float) -> None:
        self.latitude = lat
        self.longitude = lon
        self.location = LocationPoint.of(lon, lat)

    def set_area(self, coordinates_list: list[tuple[float, float]]) -> None:
        self.polygon = LocationPolygon.of(coordinates_list)


@dataclass
class UserLocation:
    id: str | None = None
    user_id: str | None = None
    location_id: int = 0
    update_date: datetime = field(default_factory=lambda: datetime.now(UTC))


def _geo_to_bson(value: LocationPoint | LocationPolygon | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {"type": value.type, "coordinates": value.coordinates}


def location_to_bson(entity: Location) -> dict[str, Any]:
    document: dict[str, Any] = {}
    if entity.id is not None:
        document["_id"] = ObjectId(entity.id)
    document.update(
        {
            "LocationId": entity.location_id,
            "Code": entity.code,
            "Parent_Id": ObjectId(entity.parent_id) if entity.parent_id else None,
            "Description": entity.description,
            "Latitude": entity.latitude,
            "Longitude": entity.longitude,
            "Location": _geo_to_bson(entity.location),
            "Polygon": _geo_to_bson(entity.polygon),
        }
    )
    return document


def location_from_bson(document: dict[str, Any]) -> Location:
    def geo_point(raw: dict[str, Any] | None) -> LocationPoint | None:
        return None if raw is None else LocationPoint(type=raw["type"], coordinates=raw["coordinates"])

    def geo_polygon(raw: dict[str, Any] | None) -> LocationPolygon | None:
        return None if raw is None else LocationPolygon(type=raw["type"], coordinates=raw["coordinates"])

    parent = document.get("Parent_Id")
    return Location(
        id=str(document["_id"]),
        location_id=document.get("LocationId", 0),
        code=document.get("Code"),
        parent_id=str(parent) if parent is not None else None,
        description=document.get("Description"),
        latitude=document.get("Latitude", 0.0),
        longitude=document.get("Longitude", 0.0),
        location=geo_point(document.get("Location")),
        polygon=geo_polygon(document.get("Polygon")),
    )


def user_location_to_bson(entity: UserLocation) -> dict[str, Any]:
    # [BsonIgnoreIfDefault] on Id: the _id is omitted so MongoDB preserves or
    # generates it on upsert, exactly like the .NET ReplaceOneAsync call.
    return {
        "UserId": entity.user_id,
        "LocationId": entity.location_id,
        "UpdateDate": entity.update_date,
    }


def user_location_from_bson(document: dict[str, Any]) -> UserLocation:
    update_date = document.get("UpdateDate") or datetime(1, 1, 1, tzinfo=UTC)
    if update_date.tzinfo is None:
        update_date = update_date.replace(tzinfo=UTC)
    return UserLocation(
        id=str(document["_id"]),
        user_id=document.get("UserId"),
        location_id=document.get("LocationId", 0),
        update_date=update_date,
    )


def location_payload(entity: Location) -> dict[str, Any]:
    """CamelCase ``Locations`` shape, field-for-field with the .NET model."""

    def geo_payload(value: LocationPoint | LocationPolygon | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return {"type": value.type, "coordinates": value.coordinates}

    return {
        "id": entity.id,
        "locationId": entity.location_id,
        "code": entity.code,
        "parent_Id": entity.parent_id,
        "description": entity.description,
        "latitude": entity.latitude,
        "longitude": entity.longitude,
        "location": geo_payload(entity.location),
        "polygon": geo_payload(entity.polygon),
    }


def user_location_payload(entity: UserLocation) -> dict[str, Any]:
    return {
        "id": entity.id,
        "userId": entity.user_id,
        "locationId": entity.location_id,
        "updateDate": entity.update_date,
    }
