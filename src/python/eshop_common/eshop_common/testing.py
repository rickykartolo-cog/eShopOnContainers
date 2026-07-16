"""Reusable test fixtures for services built on eshop_common.

Integration fixtures use the same dependency images as the existing test
topology: ``mcr.microsoft.com/mssql/server:2017-latest``, ``mongo``,
``redis:alpine``, ``rabbitmq:3-management-alpine``. Connection endpoints are
overridable via TEST_* environment variables so the suite runs both on a
developer host and inside docker compose.
"""

from __future__ import annotations

import os
import urllib.parse

import pytest


def sqlserver_url() -> str:
    host = os.environ.get("TEST_SQL_HOST", "127.0.0.1")
    port = os.environ.get("TEST_SQL_PORT", "1433")
    password = urllib.parse.quote_plus(os.environ.get("TEST_SQL_PASSWORD", "Pass@word"))
    return (
        f"mssql+aioodbc://sa:{password}@{host}:{port}/master"
        "?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=Optional&TrustServerCertificate=yes"
    )


def rabbitmq_host() -> str:
    return os.environ.get("TEST_RABBITMQ_HOST", "127.0.0.1")


def redis_url() -> str:
    return os.environ.get("TEST_REDIS_URL", "redis://127.0.0.1:6379/0")


def mongo_url() -> str:
    return os.environ.get("TEST_MONGO_URL", "mongodb://127.0.0.1:27017")


@pytest.fixture
async def sql_engine():
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(sqlserver_url(), pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest.fixture
async def sql_session(sql_engine):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from eshop_common.outbox import create_outbox_tables

    async with sql_engine.begin() as conn:
        await create_outbox_tables(conn)
    maker = async_sessionmaker(sql_engine, expire_on_commit=False)
    async with maker() as session:
        yield session


@pytest.fixture
async def rabbitmq_bus():
    from eshop_common.eventbus.rabbitmq import RabbitMQEventBus

    bus = RabbitMQEventBus(host=rabbitmq_host(), queue_name="eshop_common_tests")
    yield bus
    await bus.close()


@pytest.fixture
async def redis_client():
    import redis.asyncio as aioredis

    client = aioredis.from_url(redis_url())
    yield client
    await client.aclose()


@pytest.fixture
async def mongo_client():
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(mongo_url())
    yield client
    client.close()
