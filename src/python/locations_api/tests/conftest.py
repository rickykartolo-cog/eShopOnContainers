"""Shared fixtures: an in-memory Locations repository seeded with the exact
.NET seed data and implementing the geospatial semantics of the Mongo query
($geoIntersects point-in-polygon filter, $near distance ordering), plus an
in-memory event bus and a bypassed test authenticator matching the .NET
``LocationsTestsStartup`` fixed user."""

from __future__ import annotations

import math

import pytest
import pytest_asyncio
from eshop_common.config import Settings
from eshop_common.eventbus.base import EventBus, SubscriptionRegistry
from eshop_common.health.core import HealthCheckRegistry
from httpx import ASGITransport, AsyncClient

from locations_api.app import create_app
from locations_api.models import Location, UserLocation
from locations_api.service import LocationsService
from locations_api.settings import LocationSettings

TEST_USER_ID = "4611ce3f-380d-4db5-8d76-87a8689058ed"


class InMemoryEventBus(EventBus):
    def __init__(self) -> None:
        self.published = []
        self._registry = SubscriptionRegistry()

    async def publish(self, event) -> None:
        self.published.append(event)

    async def subscribe(self, event_type, handler) -> None:
        self._registry.add(event_type, handler)

    async def unsubscribe(self, event_type, handler) -> None:
        self._registry.remove(event_type, handler)

    async def start_consuming(self) -> None:
        pass

    async def close(self) -> None:
        pass


def _point_in_polygon(lon: float, lat: float, ring: list[list[float]]) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _haversine(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * math.asin(math.sqrt(a))


class InMemoryLocationsRepository:
    """Test double for LocationsRepository with the same interface and the
    geospatial behavior of the Mongo `$near` + `$geoIntersects` query."""

    def __init__(self) -> None:
        self.locations: list[Location] = []
        self.user_locations: dict[str, UserLocation] = {}
        self._id_counter = 0

    async def get(self, location_id: int) -> Location | None:
        return next((loc for loc in self.locations if loc.location_id == location_id), None)

    async def get_user_location(self, user_id: str) -> UserLocation | None:
        return self.user_locations.get(user_id)

    async def get_location_list(self) -> list[Location]:
        return list(self.locations)

    async def get_current_user_regions_list(self, longitude: float, latitude: float) -> list[Location]:
        matches = [
            loc
            for loc in self.locations
            if loc.polygon is not None and _point_in_polygon(longitude, latitude, loc.polygon.coordinates[0])
        ]
        matches.sort(key=lambda loc: _haversine(longitude, latitude, loc.longitude, loc.latitude))
        return matches

    async def add_user_location(self, user_location: UserLocation) -> None:
        await self.update_user_location(user_location)

    async def update_user_location(self, user_location: UserLocation) -> None:
        existing = self.user_locations.get(user_location.user_id or "")
        if existing is not None:
            user_location.id = existing.id
        elif user_location.id is None:
            self._id_counter += 1
            user_location.id = f"{self._id_counter:024x}"
        self.user_locations[user_location.user_id or ""] = user_location


async def seed_in_memory(repository: InMemoryLocationsRepository) -> None:
    from locations_api import seed as seed_module

    entries = [
        (1, "NA", "North America", -103.219329, 48.803281, seed_module.NORTH_AMERICA, None),
        (2, "US", "United States", -101.357386, 41.650455, seed_module.UNITED_STATES, 1),
        (3, "WHT", "Washington", -119.542781, 47.223652, seed_module.WASHINGTON, 2),
        (4, "SEAT", "Seattle", -122.330747, 47.603111, seed_module.SEATTLE, 3),
        (5, "REDM", "Redmond", -122.122887, 47.674961, seed_module.REDMOND, 3),
        (7, "SA", "South America", -60.328704, -16.809748, seed_module.SOUTH_AMERICA, None),
        (8, "AFC", "Africa", 19.475383, 13.063667, seed_module.AFRICA, None),
        (9, "EU", "Europe", 13.147258, 49.947844, seed_module.EUROPE, None),
        (10, "AS", "Asia", 97.522257, 56.069107, seed_module.ASIA, None),
        (11, "AUS", "Australia", 133.733195, -25.010726, seed_module.AUSTRALIA, None),
        (6, "BCN", "Barcelona", 2.156453, 41.395226, seed_module.BARCELONA, None),
    ]
    ids: dict[int, str] = {}
    for index, (location_id, code, description, lon, lat, area, parent) in enumerate(entries, start=1):
        entity = Location(
            id=f"{index:024x}",
            location_id=location_id,
            code=code,
            description=description,
            parent_id=ids.get(parent) if parent else None,
        )
        entity.set_location(lon, lat)
        entity.set_area(area)
        ids[location_id] = entity.id
        repository.locations.append(entity)


@pytest.fixture
def location_settings() -> LocationSettings:
    return LocationSettings(
        Settings(
            {
                "ConnectionString": "mongodb://unused-in-tests",
                "Database": "LocationsDb",
                "identityUrl": "http://identity-api",
                "IdentityUrlExternal": "http://localhost:5105",
                "EventBusConnection": "unused-in-tests",
                "SubscriptionClientName": "Locations",
            }
        )
    )


@pytest_asyncio.fixture
async def repository() -> InMemoryLocationsRepository:
    repo = InMemoryLocationsRepository()
    await seed_in_memory(repo)
    return repo


@pytest.fixture
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def app(location_settings, repository, event_bus):
    async def test_authenticate(request) -> str:
        # Same fixed user as the .NET LocationsTestsStartup middleware.
        return TEST_USER_ID

    service = LocationsService(repository, event_bus)
    return create_app(location_settings, service, HealthCheckRegistry(), authenticator=test_authenticate)


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client
