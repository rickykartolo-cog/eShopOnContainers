"""Port of ``LocationsService``: user-region resolution, user-location upsert,
and publication of ``UserLocationUpdatedIntegrationEvent`` to Marketing."""

from __future__ import annotations

from datetime import UTC, datetime

import structlog

from locations_api.events import UserLocationDetails, UserLocationUpdatedIntegrationEvent
from locations_api.models import Location, UserLocation
from locations_api.repository import LocationsRepository

logger = structlog.get_logger(__name__)


class LocationDomainException(Exception):
    """Exception type for app exceptions (mapped to 400 like the .NET filter)."""


class LocationsService:
    def __init__(self, repository: LocationsRepository, event_bus) -> None:
        self._repository = repository
        self._event_bus = event_bus

    async def get_location(self, location_id: int) -> Location | None:
        return await self._repository.get(location_id)

    async def get_user_location(self, user_id: str) -> UserLocation | None:
        return await self._repository.get_user_location(user_id)

    async def get_all_locations(self) -> list[Location]:
        return await self._repository.get_location_list()

    async def add_or_update_user_location(self, user_id: str, longitude: float, latitude: float) -> bool:
        # Ordered list of regions the user currently is within (nearest first).
        current_list = await self._repository.get_current_user_regions_list(longitude, latitude)
        if current_list is None:
            raise LocationDomainException("User current area not found")

        user_location = await self._repository.get_user_location(user_id) or UserLocation()
        user_location.user_id = user_id
        user_location.location_id = current_list[0].location_id
        user_location.update_date = datetime.now(UTC)
        await self._repository.update_user_location(user_location)

        await self._publish_user_location_updated(user_id, current_list)
        return True

    async def _publish_user_location_updated(self, user_id: str, new_locations: list[Location]) -> None:
        event = UserLocationUpdatedIntegrationEvent(
            UserId=user_id,
            LocationList=[
                UserLocationDetails(
                    LocationId=location.location_id,
                    Code=location.code,
                    Description=location.description,
                )
                for location in new_locations
            ],
        )
        logger.info("publishing_integration_event", event_id=str(event.id), app_name="Locations.API")
        await self._event_bus.publish(event)
