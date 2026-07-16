"""Service entrypoint: /hc + /liveness on PORT (80) like the .NET host, plus the
grace-period polling loop. Health-check names match the .NET registration:
``self``, ``OrderingTaskDB-check``, ``orderingtask-rabbitmqbus-check``."""

from __future__ import annotations

import asyncio

import structlog
import uvicorn
from eshop_common.config import ServiceSettings
from eshop_common.eventbus.rabbitmq import RabbitMQEventBus
from eshop_common.health.checks import RabbitMQHealthCheck, SqlServerHealthCheck
from eshop_common.health.core import HealthCheckRegistry
from eshop_common.template import create_service_app
from sqlalchemy.ext.asyncio import create_async_engine
from tenacity import retry, stop_after_attempt, wait_exponential

from ordering_backgroundtasks.settings import BackgroundTaskSettings
from ordering_backgroundtasks.worker import GracePeriodManager

logger = structlog.get_logger(__name__)

_startup_retry = retry(
    stop=stop_after_attempt(12),
    wait=wait_exponential(multiplier=1, min=1, max=15),
    reraise=True,
)


def build_health_registry(settings: BackgroundTaskSettings, engine) -> HealthCheckRegistry:
    registry = HealthCheckRegistry()  # registers the "self" check
    registry.add(SqlServerHealthCheck(engine, name="OrderingTaskDB-check"))
    if not settings.azure_service_bus_enabled:
        registry.add(
            RabbitMQHealthCheck(
                host=settings.event_bus_connection,
                username=settings.event_bus_username,
                password=settings.event_bus_password,
                name="orderingtask-rabbitmqbus-check",
            )
        )
    return registry


async def main() -> None:
    settings = BackgroundTaskSettings()
    engine = create_async_engine(settings.sqlalchemy_url(), pool_pre_ping=True, pool_recycle=1800)

    event_bus = RabbitMQEventBus(
        host=settings.event_bus_connection,
        queue_name=settings.subscription_client_name,
        username=settings.event_bus_username,
        password=settings.event_bus_password,
        retry_count=settings.event_bus_retry_count,
    )

    manager = GracePeriodManager(
        engine,
        event_bus,
        grace_period_time=settings.grace_period_time,
        check_update_time_ms=settings.check_update_time,
    )

    worker_task: asyncio.Task | None = None

    async def on_startup(app) -> None:
        nonlocal worker_task
        worker_task = asyncio.create_task(manager.run())
        logger.info("ordering_backgroundtasks_started")

    async def on_shutdown(app) -> None:
        if worker_task is not None:
            worker_task.cancel()
        await event_bus.close()
        await engine.dispose()

    health = build_health_registry(settings, engine)
    app = create_service_app(
        "Ordering Background Tasks",
        settings=ServiceSettings(settings.settings),
        health=health,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )

    config = uvicorn.Config(app, host="0.0.0.0", port=settings.http_port, log_config=None)
    await uvicorn.Server(config).serve()


if __name__ == "__main__":
    asyncio.run(main())
