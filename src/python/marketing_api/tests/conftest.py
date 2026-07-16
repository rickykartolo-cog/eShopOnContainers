"""Shared fixtures: in-memory SQLite marketing database (unit tests) seeded like
the .NET ``MarketingContextSeed`` preconfigured data, an in-memory Mongo
(``mongomock-motor``) read model, an in-memory event bus, and the
``AutoAuthorizeMiddleware`` parity user resolver (sub ``1234``)."""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from eshop_common.config import Settings
from eshop_common.eventbus.base import EventBus, SubscriptionRegistry
from eshop_common.health.core import HealthCheckRegistry
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient
from sqlalchemy.ext.asyncio import create_async_engine

from marketing_api import models as models_module
from marketing_api.app import create_app
from marketing_api.db import create_session_factory
from marketing_api.models import Base
from marketing_api.read_model import MarketingDataRepository
from marketing_api.seed import seed as seed_marketing
from marketing_api.settings import MarketingSettings

AUTO_AUTHORIZED_USER = "1234"


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

    async def deliver(self, event_name: str, body: bytes) -> None:
        event_type = self._registry.event_type(event_name)
        assert event_type is not None
        event = event_type.from_json(body.decode("utf-8"))
        for handler in self._registry.handlers(event_name):
            await handler(event)


@pytest.fixture
def marketing_settings() -> MarketingSettings:
    return MarketingSettings(
        Settings(
            {
                "ConnectionString": "unused-in-tests",
                "MongoConnectionString": "unused-in-tests",
                "MongoDatabase": "MarketingDb",
                "EventBusConnection": "unused-in-tests",
                "SubscriptionClientName": "Marketing",
                "identityUrl": "http://localhost:5105",
                "PicBaseUrl": "http://localhost:5110/api/v1/campaigns/[0]/pic/",
                "AzureStorageEnabled": "False",
            }
        )
    )


@pytest.fixture
def hilo_without_sequence(monkeypatch):
    """SQLite has no sequences; hand each generator a preallocated block starting
    at 1 so the seed produces the .NET ids (campaigns 1..2, rules 1..2)."""
    for generator in (models_module.campaign_hilo, models_module.rule_hilo):
        monkeypatch.setattr(generator, "_next", 1)
        monkeypatch.setattr(generator, "_max", 1_000_000)
        monkeypatch.setattr(generator, "_lock", asyncio.Lock())


@pytest_asyncio.fixture
async def session_factory(hilo_without_sequence):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    yield factory
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded_session_factory(session_factory):
    async with session_factory() as session:
        await seed_marketing(session)
    return session_factory


@pytest.fixture
def mongo_database():
    return AsyncMongoMockClient()["MarketingDb"]


@pytest.fixture
def repository(mongo_database) -> MarketingDataRepository:
    return MarketingDataRepository(mongo_database)


@pytest.fixture
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


async def _auto_authorize(_request) -> str:
    return AUTO_AUTHORIZED_USER


@pytest.fixture
def app(marketing_settings, seeded_session_factory, repository, event_bus):
    health = HealthCheckRegistry()
    return create_app(
        marketing_settings,
        seeded_session_factory,
        health,
        repository,
        event_bus=event_bus,
        user_resolver=_auto_authorize,
    )


@pytest.fixture
def anonymous_app(marketing_settings, seeded_session_factory, repository, event_bus):
    async def no_user(_request) -> None:
        return None

    health = HealthCheckRegistry()
    return create_app(
        marketing_settings,
        seeded_session_factory,
        health,
        repository,
        event_bus=event_bus,
        user_resolver=no_user,
    )


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


@pytest_asyncio.fixture
async def anonymous_client(anonymous_app):
    transport = ASGITransport(app=anonymous_app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client
