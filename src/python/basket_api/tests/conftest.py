"""Shared fixtures: fakeredis-backed repository, in-memory event bus, and a
stub bearer authenticator producing the same claims IdentityServer4 issues."""

from __future__ import annotations

import fakeredis.aioredis
import pytest
import pytest_asyncio
from eshop_common.config import Settings
from eshop_common.eventbus.base import EventBus, SubscriptionRegistry
from eshop_common.health.core import HealthCheckRegistry
from fastapi import Request, Response
from httpx import ASGITransport, AsyncClient

from basket_api.app import create_app
from basket_api.auth import challenge
from basket_api.repository import RedisBasketRepository
from basket_api.settings import BasketSettings

TEST_USER_ID = "e0431a92-9d0f-4b4a-b8f0-58e0b0f2e6a5"
TEST_USER_NAME = "alice@eshop"
TEST_TOKEN = "test-token"


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


class StubAuthenticator:
    """Enforces the bearer scheme like JwtBearer, returning fixed claims."""

    async def authenticate(self, request: Request) -> dict | Response:
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return challenge()
        if token != TEST_TOKEN:
            return challenge("invalid_token")
        return {"sub": TEST_USER_ID, "unique_name": TEST_USER_NAME, "aud": "basket"}


@pytest.fixture
def basket_settings() -> BasketSettings:
    return BasketSettings(
        Settings(
            {
                "ConnectionString": "unused-in-tests",
                "EventBusConnection": "unused-in-tests",
                "SubscriptionClientName": "Basket",
                "identityUrl": "http://identity-api",
                "IdentityUrlExternal": "http://localhost:5105",
            }
        )
    )


@pytest_asyncio.fixture
async def redis_client():
    client = fakeredis.aioredis.FakeRedis()
    yield client
    await client.aclose()


@pytest.fixture
def repository(redis_client) -> RedisBasketRepository:
    return RedisBasketRepository(redis_client)


@pytest.fixture
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def app(basket_settings, repository, event_bus):
    health = HealthCheckRegistry()
    return create_app(basket_settings, repository, health, StubAuthenticator(), event_bus=event_bus)


@pytest_asyncio.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}
