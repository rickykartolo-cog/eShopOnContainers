"""Port of ``CatalogIntegrationEventService``: atomic domain-change + outbox
insert (`SaveEventAndCatalogContextChangesAsync`), then publish-after-commit
with ``InProgress`` → ``Published``/``PublishedFailed`` state tracking."""

from __future__ import annotations

import uuid

import structlog
from eshop_common.eventbus.base import EventBus
from eshop_common.events import IntegrationEvent
from eshop_common.outbox import IntegrationEventLogService
from eshop_common.outbox import OutboxPublisher as _OutboxPublisher
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class CatalogIntegrationEventService:
    def __init__(self, session: AsyncSession, event_bus: EventBus) -> None:
        self._session = session
        self._log_service = IntegrationEventLogService(session)
        self._publisher = _OutboxPublisher(self._log_service, event_bus)
        self._transaction_id: uuid.UUID | None = None

    async def save_event_and_catalog_context_changes(self, event: IntegrationEvent) -> None:
        """The domain data mutation (pending in the session) and the outbox entry
        commit in the SAME database transaction, matching
        ``SaveEventAndCatalogContextChangesAsync``."""
        self._transaction_id = uuid.uuid4()
        await self._log_service.save_event(event, self._transaction_id)
        await self._session.commit()

    async def publish_through_event_bus(self, event: IntegrationEvent) -> None:
        logger.info("publishing_integration_event", event_id=str(event.id), event_name=type(event).event_name())
        assert self._transaction_id is not None, "save_event_and_catalog_context_changes must run first"
        await self._publisher.publish_events_through_event_bus(self._transaction_id)
