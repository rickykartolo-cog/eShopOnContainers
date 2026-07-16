"""Async engine/session factory and non-destructive database bootstrap.

The primary deployment path runs against a database already created by the .NET
migrations/seeders (§6.4): bootstrap detects the existing schema and performs no
DDL. Only when absent does it emit DDL matching the frozen dump
(`contracts/db/ordering.sqlschema.txt`) byte-for-byte at the metadata level,
including the EF migrations history rows so a later .NET rollback sees a fully
migrated database.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from tenacity import retry, stop_after_attempt, wait_fixed

logger = structlog.get_logger(__name__)

ORDERING_MIGRATIONS = [
    ("20170208181933_Initial", "1.1.0-rtm-22752"),
    ("20170303085729_RequestsTable", "1.1.0-rtm-22752"),
    ("20170313100034_Domain_events", "1.1.0-rtm-22752"),
    ("20170330131634_IntegrationEventInitial", "1.1.1"),
    ("20170403082405_NoBuyerPropertyInOrder", "1.1.0-rtm-22752"),
    ("20170511112333_AddOrderDescription", "1.1.1"),
    ("20170713111342_AdressAsValueObject", "2.0.0-preview2-25794"),
    ("20180412143935_NamePropertyInBuyer", "2.0.1-rtm-125"),
    ("20190507185219_AddTransactionId", "2.2.3-servicing-35854"),
    ("20190808132242_Change_Relation_Of_Orders", "3.0.0-preview7.19362.6"),
]

_DDL = [
    """CREATE TABLE [__EFMigrationsHistory] (
        [MigrationId] nvarchar(150) NOT NULL,
        [ProductVersion] nvarchar(32) NOT NULL,
        CONSTRAINT [PK___EFMigrationsHistory] PRIMARY KEY ([MigrationId]))""",
    "EXEC('CREATE SCHEMA [ordering]')",
    "CREATE SEQUENCE [dbo].[orderitemseq] START WITH 1 INCREMENT BY 10",
    "CREATE SEQUENCE [ordering].[buyerseq] START WITH 1 INCREMENT BY 10",
    "CREATE SEQUENCE [ordering].[orderseq] START WITH 1 INCREMENT BY 10",
    "CREATE SEQUENCE [ordering].[paymentseq] START WITH 1 INCREMENT BY 10",
    """CREATE TABLE [ordering].[buyers] (
        [Id] int NOT NULL,
        [IdentityGuid] nvarchar(200) NOT NULL,
        [Name] nvarchar(max) NULL,
        CONSTRAINT [PK_buyers] PRIMARY KEY ([Id]))""",
    "CREATE UNIQUE INDEX [IX_buyers_IdentityGuid] ON [ordering].[buyers] ([IdentityGuid])",
    """CREATE TABLE [ordering].[cardtypes] (
        [Id] int NOT NULL DEFAULT 1,
        [Name] nvarchar(200) NOT NULL,
        CONSTRAINT [PK_cardtypes] PRIMARY KEY ([Id]))""",
    """CREATE TABLE [ordering].[orderstatus] (
        [Id] int NOT NULL DEFAULT 1,
        [Name] nvarchar(200) NOT NULL,
        CONSTRAINT [PK_orderstatus] PRIMARY KEY ([Id]))""",
    """CREATE TABLE [ordering].[paymentmethods] (
        [Id] int NOT NULL,
        [Alias] nvarchar(200) NOT NULL,
        [BuyerId] int NOT NULL,
        [CardHolderName] nvarchar(200) NOT NULL,
        [CardNumber] nvarchar(25) NOT NULL,
        [CardTypeId] int NOT NULL,
        [Expiration] datetime2 NOT NULL,
        CONSTRAINT [PK_paymentmethods] PRIMARY KEY ([Id]),
        CONSTRAINT [FK_paymentmethods_buyers_BuyerId] FOREIGN KEY ([BuyerId])
            REFERENCES [ordering].[buyers] ([Id]) ON DELETE CASCADE,
        CONSTRAINT [FK_paymentmethods_cardtypes_CardTypeId] FOREIGN KEY ([CardTypeId])
            REFERENCES [ordering].[cardtypes] ([Id]) ON DELETE CASCADE)""",
    "CREATE INDEX [IX_paymentmethods_BuyerId] ON [ordering].[paymentmethods] ([BuyerId])",
    "CREATE INDEX [IX_paymentmethods_CardTypeId] ON [ordering].[paymentmethods] ([CardTypeId])",
    """CREATE TABLE [ordering].[orders] (
        [Id] int NOT NULL,
        [BuyerId] int NULL,
        [OrderDate] datetime2 NOT NULL,
        [OrderStatusId] int NOT NULL,
        [PaymentMethodId] int NULL,
        [Description] nvarchar(max) NULL,
        [Address_City] nvarchar(max) NULL,
        [Address_Country] nvarchar(max) NULL,
        [Address_State] nvarchar(max) NULL,
        [Address_Street] nvarchar(max) NULL,
        [Address_ZipCode] nvarchar(max) NULL,
        CONSTRAINT [PK_orders] PRIMARY KEY ([Id]),
        CONSTRAINT [FK_orders_buyers_BuyerId] FOREIGN KEY ([BuyerId])
            REFERENCES [ordering].[buyers] ([Id]),
        CONSTRAINT [FK_orders_orderstatus_OrderStatusId] FOREIGN KEY ([OrderStatusId])
            REFERENCES [ordering].[orderstatus] ([Id]) ON DELETE CASCADE)""",
    "CREATE INDEX [IX_orders_BuyerId] ON [ordering].[orders] ([BuyerId])",
    "CREATE INDEX [IX_orders_OrderStatusId] ON [ordering].[orders] ([OrderStatusId])",
    "CREATE INDEX [IX_orders_PaymentMethodId] ON [ordering].[orders] ([PaymentMethodId])",
    """CREATE TABLE [ordering].[orderItems] (
        [Id] int NOT NULL,
        [Discount] decimal(18,2) NOT NULL,
        [OrderId] int NOT NULL,
        [PictureUrl] nvarchar(max) NULL,
        [ProductId] int NOT NULL,
        [ProductName] nvarchar(max) NOT NULL,
        [UnitPrice] decimal(18,2) NOT NULL,
        [Units] int NOT NULL,
        CONSTRAINT [PK_orderItems] PRIMARY KEY ([Id]),
        CONSTRAINT [FK_orderItems_orders_OrderId] FOREIGN KEY ([OrderId])
            REFERENCES [ordering].[orders] ([Id]) ON DELETE CASCADE)""",
    "CREATE INDEX [IX_orderItems_OrderId] ON [ordering].[orderItems] ([OrderId])",
    """CREATE TABLE [ordering].[requests] (
        [Id] uniqueidentifier NOT NULL,
        [Name] nvarchar(max) NOT NULL,
        [Time] datetime2 NOT NULL,
        CONSTRAINT [PK_requests] PRIMARY KEY ([Id]))""",
    """CREATE TABLE [IntegrationEventLog] (
        [EventId] uniqueidentifier NOT NULL,
        [Content] nvarchar(max) NOT NULL,
        [CreationTime] datetime2 NOT NULL,
        [EventTypeName] nvarchar(max) NOT NULL,
        [State] int NOT NULL,
        [TimesSent] int NOT NULL,
        [TransactionId] nvarchar(max) NULL,
        CONSTRAINT [PK_IntegrationEventLog] PRIMARY KEY ([EventId]))""",
]

CARD_TYPE_SEED = [(1, "Amex"), (2, "Visa"), (3, "MasterCard")]
ORDER_STATUS_SEED = [
    (1, "submitted"),
    (2, "awaitingvalidation"),
    (3, "stockconfirmed"),
    (4, "paid"),
    (5, "shipped"),
    (6, "cancelled"),
]


@retry(reraise=True, stop=stop_after_attempt(30), wait=wait_fixed(3))
def ensure_ordering_database_exists(connection_string: str) -> None:
    """Create the OrderingDb database when absent (mirrors EF ``Migrate()``).
    Connects to ``master`` with the same credentials."""
    import pyodbc

    parts = {k.strip().lower(): v.strip() for k, _, v in
             (chunk.partition("=") for chunk in connection_string.split(";") if "=" in chunk)}
    database = parts.get("database", parts.get("initial catalog", ""))
    server = parts.get("server", "localhost")
    port = "1433"
    if "," in server:
        server, port = server.split(",", 1)
    if server.lower().startswith("tcp:"):
        server = server[4:]
    odbc = (
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server=tcp:{server},{port};Database=master;"
        f"Uid={parts.get('user id', parts.get('uid', ''))};"
        f"Pwd={parts.get('password', parts.get('pwd', ''))};"
        "Encrypt=Optional;TrustServerCertificate=yes;"
    )
    with pyodbc.connect(odbc, autocommit=True, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT db_id(?)", database)
        if cursor.fetchone()[0] is None:
            cursor.execute(f"CREATE DATABASE [{database}]")
            logger.info("ordering_database_created", database=database)


def create_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True, pool_recycle=1800)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _schema_exists(engine: AsyncEngine) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = 'ordering' AND TABLE_NAME = 'orders'"
            )
        )
        return bool(result.scalar())


@retry(reraise=True, stop=stop_after_attempt(30), wait=wait_fixed(3))
async def ensure_database(engine: AsyncEngine) -> bool:
    """Non-destructive bootstrap. Returns True when this process created the schema."""
    if await _schema_exists(engine):
        logger.info("ordering_schema_present", created=False)
        return False
    async with engine.begin() as conn:
        for statement in _DDL:
            await conn.execute(text(statement))
        for migration_id, product_version in ORDERING_MIGRATIONS:
            await conn.execute(
                text(
                    "INSERT INTO [__EFMigrationsHistory] (MigrationId, ProductVersion) "
                    "VALUES (:mid, :ver)"
                ),
                {"mid": migration_id, "ver": product_version},
            )
    logger.info("ordering_schema_created", created=True)
    return True


async def seed(session: AsyncSession) -> None:
    """Port of ``OrderingContextSeed``: predefined card types and order status."""
    existing = (await session.execute(text("SELECT COUNT(*) FROM ordering.cardtypes"))).scalar()
    if not existing:
        for card_id, name in CARD_TYPE_SEED:
            await session.execute(
                text("INSERT INTO ordering.cardtypes (Id, Name) VALUES (:id, :name)"),
                {"id": card_id, "name": name},
            )
    existing = (await session.execute(text("SELECT COUNT(*) FROM ordering.orderstatus"))).scalar()
    if not existing:
        for status_id, name in ORDER_STATUS_SEED:
            await session.execute(
                text("INSERT INTO ordering.orderstatus (Id, Name) VALUES (:id, :name)"),
                {"id": status_id, "name": name},
            )
    await session.commit()
