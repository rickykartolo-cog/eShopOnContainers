"""Port of ``LocationsContextSeed``: identical documents (codes, descriptions,
LocationIds, parent chain, center points, polygons) and the ``Location``
2dsphere index, inserted only when the ``Locations`` collection is empty."""

from __future__ import annotations

from pymongo import GEOSPHERE

from locations_api.models import Location, location_to_bson
from locations_api.repository import LocationsRepository

Coordinates = list[tuple[float, float]]

NORTH_AMERICA: Coordinates = [
    (-168.07786, 68.80277),
    (-119.60378, 32.7561),
    (-116.01966, 28.94642),
    (-98.52265, 14.49378),
    (-71.18188, 34.96278),
    (-51.97606, 48.24377),
    (-75.39806, 72.93141),
    (-168.07786, 68.80277),
]

SOUTH_AMERICA: Coordinates = [
    (-91.43724, 13.29007),
    (-87.96315, -27.15081),
    (-78.75404, -50.71852),
    (-59.14765, -58.50773),
    (-50.08813, -42.22419),
    (-37.21044, -22.56725),
    (-36.61675, -0.38594),
    (-44.46056, -16.6746),
    (-91.43724, 13.29007),
]

AFRICA: Coordinates = [
    (-12.68724, 34.05892),
    (-18.33301, 20.77313),
    (-14.13503, 6.21292),
    (1.40221, -14.23693),
    (22.41485, -35.55408),
    (51.86499, -25.39831),
    (53.49269, 4.59405),
    (35.102, 26.14685),
    (21.63319, 33.75767),
    (6.58235, 37.05665),
    (-12.68724, 34.05892),
]

EUROPE: Coordinates = [
    (-11.73143, 35.27646),
    (-10.84462, 35.25123),
    (-10.09927, 35.26833),
    (49.00838, 36.56984),
    (36.63837, 71.69807),
    (-10.88788, 61.13851),
    (-11.73143, 35.27646),
]

ASIA: Coordinates = [
    (31.1592, 45.91629),
    (32.046, 45.89479),
    (62.32261, -4.45013),
    (154.47713, 35.14525),
    (-166.70788, 68.62211),
    (70.38837, 75.89335),
    (32.00274, 67.23428),
    (31.1592, 45.91629),
]

AUSTRALIA: Coordinates = [
    (100.76857, -45.74117),
    (101.65538, -45.76273),
    (167.08823, -50.66317),
    (174.16463, -34.62579),
    (160.94837, -5.01004),
    (139.29462, -7.86376),
    (101.61212, -11.44654),
    (100.76857, -45.74117),
]

UNITED_STATES: Coordinates = [
    (-62.88205, 48.7985),
    (-129.3132, 48.76513),
    (-120.9496, 30.12256),
    (-111.3944, 30.87114),
    (-78.11975, 24.24979),
    (-62.88205, 48.7985),
]

SEATTLE: Coordinates = [
    (-122.36238, 47.82929),
    (-122.42091, 47.6337),
    (-122.37371, 47.45224),
    (-122.20788, 47.50259),
    (-122.26934, 47.73644),
    (-122.36238, 47.82929),
]

REDMOND: Coordinates = [
    (-122.15432, 47.73148),
    (-122.17673, 47.72559),
    (-122.16904, 47.67851),
    (-122.16136, 47.65036),
    (-122.15604, 47.62746),
    (-122.01562, 47.63463),
    (-122.04961, 47.74244),
    (-122.15432, 47.73148),
]

WASHINGTON: Coordinates = [
    (-124.68633, 48.8943),
    (-124.32962, 45.66613),
    (-116.73824, 45.93384),
    (-116.96912, 49.04282),
    (-124.68633, 48.8943),
]

BARCELONA: Coordinates = [
    (2.033879, 41.383858),
    (2.113741, 41.419068),
    (2.188778, 41.451153),
    (2.235266, 41.418033),
    (2.137101, 41.299536),
    (2.033879, 41.383858),
]


def _location(
    location_id: int,
    code: str,
    description: str,
    lon: float,
    lat: float,
    area: Coordinates,
    parent_id: str | None = None,
) -> Location:
    entity = Location(location_id=location_id, code=code, description=description, parent_id=parent_id)
    entity.set_location(lon, lat)
    entity.set_area(area)
    return entity


async def seed(repository: LocationsRepository) -> None:
    locations = repository.database.get_collection("Locations")
    if await locations.count_documents({}) > 0:
        return

    await locations.create_index([("Location", GEOSPHERE)])

    async def insert(entity: Location) -> str:
        result = await locations.insert_one(location_to_bson(entity))
        return str(result.inserted_id)

    # North America -> United States -> Washington -> Seattle / Redmond
    na_id = await insert(_location(1, "NA", "North America", -103.219329, 48.803281, NORTH_AMERICA))
    us_id = await insert(_location(2, "US", "United States", -101.357386, 41.650455, UNITED_STATES, na_id))
    wht_id = await insert(_location(3, "WHT", "Washington", -119.542781, 47.223652, WASHINGTON, us_id))
    await insert(_location(4, "SEAT", "Seattle", -122.330747, 47.603111, SEATTLE, wht_id))
    await insert(_location(5, "REDM", "Redmond", -122.122887, 47.674961, REDMOND, wht_id))
    await insert(_location(7, "SA", "South America", -60.328704, -16.809748, SOUTH_AMERICA))
    await insert(_location(8, "AFC", "Africa", 19.475383, 13.063667, AFRICA))
    await insert(_location(9, "EU", "Europe", 13.147258, 49.947844, EUROPE))
    await insert(_location(10, "AS", "Asia", 97.522257, 56.069107, ASIA))
    await insert(_location(11, "AUS", "Australia", 133.733195, -25.010726, AUSTRALIA))
    await insert(_location(6, "BCN", "Barcelona", 2.156453, 41.395226, BARCELONA))
