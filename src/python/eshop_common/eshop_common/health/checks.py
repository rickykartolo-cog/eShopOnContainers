"""Dependency health-check adapters: SQL Server, MongoDB, Redis, RabbitMQ,
Azure Service Bus, and external HTTP dependencies."""

from __future__ import annotations

from collections.abc import Iterable

import httpx

from eshop_common.health.core import HealthCheck, HealthResult


class SqlServerHealthCheck(HealthCheck):
    """SELECT 1 probe over the async ODBC engine (matches AspNetCore.HealthChecks.SqlServer)."""

    def __init__(self, engine, name: str = "sqlserver", tags: Iterable[str] = ()) -> None:
        super().__init__(name, tags)
        self._engine = engine

    async def check(self) -> HealthResult:
        from sqlalchemy import text

        try:
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return HealthResult.healthy()
        except Exception as exc:
            return HealthResult.unhealthy(description=str(exc), exception=str(exc))


class MongoHealthCheck(HealthCheck):
    def __init__(self, client, name: str = "mongodb", tags: Iterable[str] = ()) -> None:
        super().__init__(name, tags)
        self._client = client

    async def check(self) -> HealthResult:
        try:
            await self._client.admin.command("ping")
            return HealthResult.healthy()
        except Exception as exc:
            return HealthResult.unhealthy(description=str(exc), exception=str(exc))


class RedisHealthCheck(HealthCheck):
    def __init__(self, redis_client, name: str = "redis", tags: Iterable[str] = ()) -> None:
        super().__init__(name, tags)
        self._redis = redis_client

    async def check(self) -> HealthResult:
        try:
            await self._redis.ping()
            return HealthResult.healthy()
        except Exception as exc:
            return HealthResult.unhealthy(description=str(exc), exception=str(exc))


class RabbitMQHealthCheck(HealthCheck):
    def __init__(
        self,
        host: str,
        username: str | None = None,
        password: str | None = None,
        port: int = 5672,
        name: str = "rabbitmqbus",
        tags: Iterable[str] = (),
    ) -> None:
        super().__init__(name, tags)
        self._host = host
        self._port = port
        self._username = username or "guest"
        self._password = password or "guest"

    async def check(self) -> HealthResult:
        import aio_pika

        try:
            connection = await aio_pika.connect(
                host=self._host, port=self._port, login=self._username, password=self._password
            )
            await connection.close()
            return HealthResult.healthy()
        except Exception as exc:
            return HealthResult.unhealthy(description=str(exc), exception=str(exc))


class ServiceBusHealthCheck(HealthCheck):
    def __init__(self, connection_string: str, topic_name: str = "eshop_event_bus",
                 name: str = "servicebus", tags: Iterable[str] = ()) -> None:
        super().__init__(name, tags)
        self._connection_string = connection_string
        self._topic_name = topic_name

    async def check(self) -> HealthResult:
        from azure.servicebus.aio.management import ServiceBusAdministrationClient

        try:
            async with ServiceBusAdministrationClient.from_connection_string(
                self._connection_string
            ) as admin:
                await admin.get_topic(self._topic_name)
            return HealthResult.healthy()
        except Exception as exc:
            return HealthResult.unhealthy(description=str(exc), exception=str(exc))


class HttpUrlHealthCheck(HealthCheck):
    """Equivalent of ``AddUrlGroup``: GET the URL and expect a 2xx response."""

    def __init__(self, url: str, name: str, tags: Iterable[str] = (), timeout: float = 10.0) -> None:
        super().__init__(name, tags)
        self._url = url
        self._timeout = timeout

    async def check(self) -> HealthResult:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(self._url)
            if response.is_success:
                return HealthResult.healthy()
            return HealthResult.unhealthy(
                description=f"Discover endpoint is not responding with 200 OK, the current status is "
                f"{response.status_code} and the content {response.text}"
            )
        except Exception as exc:
            return HealthResult.unhealthy(description=str(exc), exception=str(exc))
