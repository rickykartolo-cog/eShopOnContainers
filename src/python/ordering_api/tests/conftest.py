"""Shared fixtures: in-memory SQLite ordering database (attached as the
``ordering`` schema) seeded like ``OrderingContextSeed``, an in-memory event
bus, and an authenticated test app."""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from eshop_common.config import Settings
from eshop_common.eventbus.base import EventBus, SubscriptionRegistry
from eshop_common.health.core import HealthCheckRegistry
from eshop_common.outbox import OutboxBase
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import create_async_engine

from ordering_api import handlers as handlers_module
from ordering_api import models as models_module
from ordering_api.app import create_app
from ordering_api.db import create_session_factory
from ordering_api.db import seed as seed_ordering
from ordering_api.handlers import build_mediator
from ordering_api.models import Base
from ordering_api.settings import OrderingSettings

TEST_USER_ID = "e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5"
TEST_USER_NAME = "alice@eshop"


class InMemoryEventBus(EventBus):
    def __init__(self) -> None:
        self.published = []
        self.fail_publish = False
        self._registry = SubscriptionRegistry()

    async def publish(self, event_) -> None:
        if self.fail_publish:
            raise ConnectionError("broker unavailable")
        self.published.append(event_)

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
        incoming = event_type.from_json(body.decode("utf-8"))
        for handler in self._registry.handlers(event_name):
            await handler(incoming)


class FakeJwtBearer:
    """Stands in for the OIDC validator: every request is an authenticated user
    with the ``sub``/``name`` claims the routes read."""

    def __init__(self, sub: str = TEST_USER_ID, name: str = TEST_USER_NAME) -> None:
        self._claims = {"sub": sub, "name": name, "aud": "orders"}

    async def __call__(self, request):
        request.state.user = self._claims
        return self._claims


@pytest.fixture
def ordering_settings() -> OrderingSettings:
    return OrderingSettings(
        Settings(
            {
                "ConnectionString": "unused-in-tests",
                "EventBusConnection": "unused-in-tests",
                "SubscriptionClientName": "Ordering",
                "identityUrl": "http://identity-api",
            }
        )
    )


@pytest.fixture
def hilo_without_sequence(monkeypatch):
    """SQLite has no sequences; hand each generator a preallocated block."""
    for generator, start in (
        (models_module.order_hilo, 10_000),
        (models_module.buyer_hilo, 20_000),
        (models_module.payment_hilo, 30_000),
        (models_module.order_item_hilo, 40_000),
    ):
        monkeypatch.setattr(generator, "_next", start)
        monkeypatch.setattr(generator, "_max", start + 1_000_000)
        monkeypatch.setattr(generator, "_lock", asyncio.Lock())


@pytest.fixture
def no_simulated_delay(monkeypatch):
    monkeypatch.setattr(handlers_module, "SIMULATED_WORK_SECONDS", 0.0)


@pytest_asyncio.fixture
async def session_factory(hilo_without_sequence, no_simulated_delay):
    engine = create_async_engine("sqlite+aiosqlite://")

    @event.listens_for(engine.sync_engine, "connect")
    def _attach_ordering_schema(dbapi_connection, _record):
        dbapi_connection.execute("ATTACH DATABASE ':memory:' AS ordering")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(OutboxBase.metadata.create_all)
    factory = create_session_factory(engine)
    async with factory() as session:
        await seed_ordering(session)
    yield factory
    await engine.dispose()


@pytest.fixture
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def mediator():
    return build_mediator()


@pytest.fixture
def app(ordering_settings, session_factory, event_bus, mediator):
    health = HealthCheckRegistry()
    return create_app(
        ordering_settings,
        session_factory,
        health,
        mediator,
        event_bus=event_bus,
        jwt_bearer=FakeJwtBearer(),
    )


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


def new_request_id() -> str:
    return str(uuid.uuid4())
