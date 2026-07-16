"""Grace-period worker: golden event parity and polling/publication behavior
(oracle: GracePeriodManagerService)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest_asyncio
from eshop_common.eventbus.base import EventBus, SubscriptionRegistry
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from ordering_backgroundtasks.events import GracePeriodConfirmedIntegrationEvent
from ordering_backgroundtasks.worker import GracePeriodManager

GOLDEN = (
    Path(__file__).resolve().parents[4]
    / "contracts"
    / "events"
    / "GracePeriodConfirmedIntegrationEvent.golden.json"
)


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


def test_grace_period_event_matches_golden():
    event = GracePeriodConfirmedIntegrationEvent(
        OrderId=42,
        Id=uuid.UUID("11111111-2222-3333-4444-555555555555"),
        CreationDate=datetime(2020, 1, 2, 3, 4, 5, 678000, tzinfo=UTC),
    )
    assert event.to_json() == GOLDEN.read_text(encoding="utf-8").strip()
    assert type(event).event_name() == "GracePeriodConfirmedIntegrationEvent"  # routing key


@pytest_asyncio.fixture
async def engine():
    """SQLite stand-in for the ordering database with the T-SQL functions the
    frozen polling query uses."""
    engine = create_async_engine("sqlite+aiosqlite://")

    from sqlalchemy import event as sa_event

    @sa_event.listens_for(engine.sync_engine, "connect")
    def _register(dbapi_connection, _record):
        dbapi_connection.execute("ATTACH DATABASE ':memory:' AS ordering")

        def datediff(unit: str, start: str, end: str) -> int:
            delta = datetime.fromisoformat(end) - datetime.fromisoformat(start)
            assert unit == "minute"
            return int(delta.total_seconds() // 60)

        dbapi_connection.create_function("DATEDIFF", 3, datediff)
        dbapi_connection.create_function("GETDATE", 0, lambda: datetime.utcnow().isoformat(sep=" "))

    async with engine.begin() as conn:
        await conn.execute(
            text("CREATE TABLE ordering.orders (Id INTEGER PRIMARY KEY, OrderDate TEXT, OrderStatusId INTEGER)")
        )
    yield engine
    await engine.dispose()


async def test_publishes_event_per_expired_submitted_order(engine, monkeypatch):
    from ordering_backgroundtasks import worker as worker_module

    # SQLite has no bare `minute` identifier; quote it as a string for the UDF.
    monkeypatch.setattr(
        worker_module.GracePeriodManager,
        "_get_confirmed_grace_period_orders",
        _sqlite_query,
    )
    bus = InMemoryEventBus()
    manager = GracePeriodManager(engine, bus, grace_period_time=1, check_update_time_ms=1000)

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO ordering.orders (Id, OrderDate, OrderStatusId) VALUES "
                "(1, '2020-01-01 00:00:00', 1), "  # expired + submitted -> published
                "(2, '2020-01-01 00:00:00', 2), "  # not submitted
                "(3, datetime('now'), 1)"  # submitted but inside grace period
            )
        )

    await manager.check_confirmed_grace_period_orders()
    assert [type(e).__name__ for e in bus.published] == ["GracePeriodConfirmedIntegrationEvent"]
    assert bus.published[0].order_id == 1


async def _sqlite_query(self) -> list[int]:
    async with self._engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT Id FROM ordering.orders "
                "WHERE DATEDIFF('minute', OrderDate, GETDATE()) >= :GracePeriodTime "
                "AND OrderStatusId = 1"
            ),
            {"GracePeriodTime": self._grace_period_time},
        )
        return [row[0] for row in result]


async def test_database_failure_is_swallowed_and_polling_continues(engine):
    bus = InMemoryEventBus()
    broken = create_async_engine("sqlite+aiosqlite:///nonexistent-dir/none.db")
    manager = GracePeriodManager(broken, bus, grace_period_time=1, check_update_time_ms=1000)
    await manager.check_confirmed_grace_period_orders()  # must not raise
    assert bus.published == []
    await broken.dispose()
