"""Integration event consumed by Marketing, byte-compatible with the frozen
golden (`contracts/events/UserLocationUpdatedIntegrationEvent.golden.json`).
The RabbitMQ routing key is the unchanged class name."""

from __future__ import annotations

from eshop_common.events import IntegrationEvent
from pydantic import BaseModel, ConfigDict, Field


class UserLocationDetails(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    location_id: int = Field(default=0, alias="LocationId")
    code: str | None = Field(default=None, alias="Code")
    description: str | None = Field(default=None, alias="Description")


class UserLocationUpdatedIntegrationEvent(IntegrationEvent):
    user_id: str | None = Field(default=None, alias="UserId")
    location_list: list[UserLocationDetails] = Field(default_factory=list, alias="LocationList")
