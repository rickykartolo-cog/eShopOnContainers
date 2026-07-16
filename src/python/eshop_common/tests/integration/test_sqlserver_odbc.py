"""Validation of the fragile async SQL Server path:
aioodbc + pyodbc + Microsoft ODBC Driver 18 against SQL Server 2017.
Versions recorded in docs/odbc-validation.md."""

import asyncio

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from eshop_common.testing import sqlserver_url

pytestmark = pytest.mark.integration


@pytest.fixture
async def engine():
    engine = create_async_engine(sqlserver_url(), pool_pre_ping=True)
    yield engine
    await engine.dispose()


async def test_async_connect_and_version(engine):
    async with engine.connect() as conn:
        version = (await conn.execute(text("SELECT @@VERSION"))).scalar_one()
    assert "SQL Server 2017" in version


async def test_typed_round_trip(engine):
    async with engine.begin() as conn:
        await conn.execute(text("IF OBJECT_ID('dbo.__eshop_odbc_test') IS NOT NULL DROP TABLE dbo.__eshop_odbc_test"))
        await conn.execute(
            text(
                "CREATE TABLE dbo.__eshop_odbc_test ("
                "Id UNIQUEIDENTIFIER PRIMARY KEY, Name NVARCHAR(50) NOT NULL, "
                "Price DECIMAL(18,2) NOT NULL, CreationTime DATETIME2 NOT NULL)"
            )
        )
        await conn.execute(
            text(
                "INSERT INTO dbo.__eshop_odbc_test VALUES "
                "(NEWID(), N'.NET Bot Black Hoodie', 19.50, SYSUTCDATETIME())"
            )
        )
    async with engine.connect() as conn:
        row = (await conn.execute(text("SELECT Name, Price FROM dbo.__eshop_odbc_test"))).one()
    assert row.Name == ".NET Bot Black Hoodie"
    assert float(row.Price) == 19.50
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE dbo.__eshop_odbc_test"))


async def test_concurrent_async_queries(engine):
    async def one(i: int) -> int:
        async with engine.connect() as conn:
            return (await conn.execute(text(f"SELECT {i}"))).scalar_one()

    assert await asyncio.gather(*[one(i) for i in range(10)]) == list(range(10))


async def test_transaction_rollback(engine):
    async with engine.begin() as conn:
        await conn.execute(text("IF OBJECT_ID('dbo.__eshop_tx_test') IS NOT NULL DROP TABLE dbo.__eshop_tx_test"))
        await conn.execute(text("CREATE TABLE dbo.__eshop_tx_test (Id INT PRIMARY KEY)"))
    try:
        with pytest.raises(RuntimeError):
            async with engine.begin() as conn:
                await conn.execute(text("INSERT INTO dbo.__eshop_tx_test VALUES (1)"))
                raise RuntimeError("force rollback")
        async with engine.connect() as conn:
            count = (await conn.execute(text("SELECT COUNT(*) FROM dbo.__eshop_tx_test"))).scalar_one()
        assert count == 0
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE dbo.__eshop_tx_test"))
