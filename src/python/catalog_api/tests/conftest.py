"""Shared fixtures: in-memory SQLite catalog database (unit tests) seeded like
the .NET ``CatalogContextSeed`` preconfigured data, plus an in-memory event bus."""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from eshop_common.config import Settings
from eshop_common.eventbus.base import EventBus, SubscriptionRegistry
from eshop_common.health.core import HealthCheckRegistry
from eshop_common.outbox import OutboxBase
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine

from catalog_api import models as models_module
from catalog_api.app import create_app
from catalog_api.db import create_session_factory
from catalog_api.models import Base
from catalog_api.seed import seed as seed_catalog
from catalog_api.settings import CatalogSettings


class InMemoryEventBus(EventBus):
    def __init__(self) -> None:
        self.published = []
        self.fail_publish = False
        self._registry = SubscriptionRegistry()

    async def publish(self, event) -> None:
        if self.fail_publish:
            raise ConnectionError("broker unavailable")
        self.published.append(event)

    async def subscribe(self, event_type, handler) -> None:
        self._registry.add(event_type, handler)

    async def unsubscribe(self, event_type, handler) -> None:
        self._registry.remove(event_type, handler)

    async def start_consuming(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def deliver(self, event_name: str, body: bytes) -> None:
        event_type = self._registry.event_type(event_name)
        assert event_type is not None
        event = event_type.from_json(body.decode("utf-8"))
        for handler in self._registry.handlers(event_name):
            await handler(event)


@pytest.fixture
def catalog_settings() -> CatalogSettings:
    return CatalogSettings(
        Settings(
            {
                "PicBaseUrl": "http://localhost:5101/api/v1/catalog/items/[0]/pic/",
                "AzureStorageEnabled": "False",
                "ConnectionString": "unused-in-tests",
                "EventBusConnection": "unused-in-tests",
                "SubscriptionClientName": "Catalog",
            }
        )
    )


@pytest.fixture
def hilo_without_sequence(monkeypatch):
    """SQLite has no sequences; hand each generator a preallocated block."""
    for generator, start in (
        (models_module.catalog_hilo, 10_000),
        (models_module.catalog_brand_hilo, 20_000),
        (models_module.catalog_type_hilo, 30_000),
    ):
        monkeypatch.setattr(generator, "_next", start)
        monkeypatch.setattr(generator, "_max", start + 1_000_000)
        monkeypatch.setattr(generator, "_lock", asyncio.Lock())


@pytest_asyncio.fixture
async def session_factory(hilo_without_sequence):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(OutboxBase.metadata.create_all)
    factory = create_session_factory(engine)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_session_factory(session_factory, catalog_settings, monkeypatch):
    # Preconfigured .NET seed uses fixed type/brand ids 1..5.
    for generator, start in (
        (models_module.catalog_brand_hilo, 1),
        (models_module.catalog_type_hilo, 1),
    ):
        monkeypatch.setattr(generator, "_next", start)
        monkeypatch.setattr(generator, "_max", start + 1_000_000)
    async with session_factory() as session:
        await seed_catalog(session, catalog_settings)
    return session_factory


@pytest.fixture
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def app(catalog_settings, seeded_session_factory, event_bus):
    health = HealthCheckRegistry()
    return create_app(catalog_settings, seeded_session_factory, health, event_bus=event_bus)


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client
