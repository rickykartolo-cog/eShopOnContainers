"""Port of ``UserLocationUpdatedIntegrationEventHandler``: replaces the user's
``Locations`` in the ``MarketingReadDataModel`` document (upsert). The write is
a whole-document location replacement keyed by ``UserId``, so at-least-once /
duplicate delivery converges to the same state with no extra side effects."""

from __future__ import annotations

import structlog
from eshop_common.eventbus.base import EventBus

from marketing_api.events import UserLocationUpdatedIntegrationEvent
from marketing_api.read_model import Location, MarketingData, MarketingDataRepository

logger = structlog.get_logger(__name__)


class MarketingEventConsumers:
    def __init__(self, repository: MarketingDataRepository, event_bus: EventBus) -> None:
        self._repository = repository
        self._event_bus = event_bus

    async def subscribe_all(self) -> None:
        await self._event_bus.subscribe(UserLocationUpdatedIntegrationEvent, self.on_user_location_updated)

    async def on_user_location_updated(self, event) -> None:
        assert isinstance(event, UserLocationUpdatedIntegrationEvent)
        user_id = event.user_id or ""
        marketing_data = await self._repository.get(user_id)
        if marketing_data is None:
            marketing_data = MarketingData(UserId=user_id)
        marketing_data.Locations = [
            Location(LocationId=details.location_id, Code=details.code, Description=details.description)
            for details in event.location_list
        ]
        await self._repository.update_location(marketing_data)
        logger.info("user_location_updated_handled", event_id=str(event.id), user_id=user_id)
