"""Shared fixtures: in-memory SQLite webhooks database, a stub OIDC validator
(the routes' auth boundary), a mock grant/hook HTTP transport, and an in-memory
event bus able to deliver raw .NET-serialized bytes (mixed-stack oracle)."""

from __future__ import annotations

import jwt as pyjwt
import pytest
import pytest_asyncio
from eshop_common.config import Settings
from eshop_common.eventbus.base import EventBus, SubscriptionRegistry
from eshop_common.health.core import HealthCheckRegistry
from httpx import ASGITransport, AsyncClient, MockTransport, Request, Response
from sqlalchemy.ext.asyncio import create_async_engine

from webhooks_api.app import create_app
from webhooks_api.db import create_session_factory
from webhooks_api.models import Base
from webhooks_api.sender import TOKEN_HEADER, WebhooksSender
from webhooks_api.settings import WebhooksSettings

USERS = {"token-alice": "alice", "token-bob": "bob"}


class StubValidator:
    """Stands in for OidcJwtValidator: maps bearer tokens to ``sub`` claims."""

    async def validate(self, token: str) -> dict:
        if token in USERS:
            return {"sub": USERS[token]}
        raise pyjwt.InvalidTokenError("unknown token")


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


class RecordingTransport:
    """Mock transport for grant-verification OPTIONS and webhook POSTs."""

    def __init__(self) -> None:
        self.requests: list[Request] = []
        self.hook_posts: list[Request] = []

    def handler(self, request: Request) -> Response:
        self.requests.append(request)
        if request.method == "OPTIONS":
            path = request.url.path
            if path.endswith("/grant-ok"):
                token = request.headers.get(TOKEN_HEADER, "")
                headers = {TOKEN_HEADER: token} if token else {}
                return Response(200, headers=headers)
            if path.endswith("/grant-noecho"):
                return Response(200)
            return Response(500)
        if request.method == "POST":
            self.hook_posts.append(request)
            return Response(200)
        return Response(404)


@pytest.fixture
def webhooks_settings() -> WebhooksSettings:
    return WebhooksSettings(
        Settings(
            {
                "ConnectionString": "unused-in-tests",
                "EventBusConnection": "unused-in-tests",
                "SubscriptionClientName": "Webhooks",
                "IdentityUrl": "http://identity-api",
                "IdentityUrlExternal": "http://localhost:5105",
            }
        )
    )


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    yield factory
    await engine.dispose()


@pytest.fixture
def transport() -> RecordingTransport:
    return RecordingTransport()


@pytest.fixture
def event_bus() -> InMemoryEventBus:
    return InMemoryEventBus()


@pytest.fixture
def sender(transport) -> WebhooksSender:
    return WebhooksSender(AsyncClient(transport=MockTransport(transport.handler)))


@pytest.fixture
def app(webhooks_settings, session_factory, transport):
    health = HealthCheckRegistry()
    return create_app(
        webhooks_settings,
        session_factory,
        health,
        jwt_validator=StubValidator(),
        grant_client=AsyncClient(transport=MockTransport(transport.handler)),
    )


@pytest_asyncio.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as http_client:
        yield http_client


def auth(token: str = "token-alice") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
