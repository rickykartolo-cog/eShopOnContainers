"""Async engine/session factory and non-destructive database bootstrap.

The primary deployment path runs against a database already created by the
.NET migrations/seeders (§6.4): bootstrap detects the existing schema and
performs no DDL. Only when the schema is absent (fresh mixed-stack compose
without the .NET image) does it emit DDL that matches the frozen schema dump
(`contracts/db/marketing.sqlschema.txt`), including the EF migrations history
rows so a later .NET rollback sees a fully migrated database.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from tenacity import retry, stop_after_attempt, wait_fixed

from marketing_api.settings import parse_ado_connection_string

logger = structlog.get_logger(__name__)

MARKETING_MIGRATIONS = [
    ("20170615163431_Init", "1.1.2"),
    ("20170629102516_added-campaign-details", "1.1.2"),
]

_DDL = [
    """CREATE TABLE [__EFMigrationsHistory] (
        [MigrationId] nvarchar(150) NOT NULL,
        [ProductVersion] nvarchar(32) NOT NULL,
        CONSTRAINT [PK___EFMigrationsHistory] PRIMARY KEY ([MigrationId]))""",
    "CREATE SEQUENCE [campaign_hilo] START WITH 1 INCREMENT BY 10",
    "CREATE SEQUENCE [rule_hilo] START WITH 1 INCREMENT BY 10",
    """CREATE TABLE [Campaign] (
        [Id] int NOT NULL,
        [Description] nvarchar(max) NOT NULL,
        [From] datetime2 NOT NULL,
        [Name] nvarchar(max) NOT NULL,
        [PictureUri] nvarchar(max) NOT NULL,
        [To] datetime2 NOT NULL,
        [DetailsUri] nvarchar(max) NULL,
        [PictureName] nvarchar(max) NULL,
        CONSTRAINT [PK_Campaign] PRIMARY KEY ([Id]))""",
    """CREATE TABLE [Rule] (
        [Id] int NOT NULL,
        [CampaignId] int NOT NULL,
        [Description] nvarchar(max) NOT NULL,
        [RuleTypeId] int NOT NULL,
        [LocationId] int NULL,
        CONSTRAINT [PK_Rule] PRIMARY KEY ([Id]),
        CONSTRAINT [FK_Rule_Campaign_CampaignId] FOREIGN KEY ([CampaignId])
            REFERENCES [Campaign] ([Id]) ON DELETE CASCADE)""",
    "CREATE INDEX [IX_Rule_CampaignId] ON [Rule] ([CampaignId])",
]


@retry(reraise=True, stop=stop_after_attempt(30), wait=wait_fixed(3))
def ensure_marketing_database_exists(connection_string: str) -> None:
    """Create the MarketingDb database when absent (mirrors EF ``Migrate()`` which
    creates the database). Connects to ``master`` with the same credentials."""
    import pyodbc

    parts = parse_ado_connection_string(connection_string)
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
            logger.info("marketing_database_created", database=database)


def create_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True, pool_recycle=1800)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def _schema_exists(engine: AsyncEngine) -> bool:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = 'Campaign'")
        )
        return bool(result.scalar())


@retry(reraise=True, stop=stop_after_attempt(30), wait=wait_fixed(3))
async def ensure_database(engine: AsyncEngine, is_sqlserver: bool = True) -> bool:
    """Non-destructive bootstrap. Returns True when this process created the schema."""
    if await _schema_exists(engine):
        logger.info("marketing_schema_present", created=False)
        return False
    if not is_sqlserver:
        raise RuntimeError("ensure_database only supports SQL Server; use test fixtures elsewhere")
    async with engine.begin() as conn:
        for statement in _DDL:
            await conn.execute(text(statement))
        for migration_id, product_version in MARKETING_MIGRATIONS:
            await conn.execute(
                text(
                    "INSERT INTO [__EFMigrationsHistory] (MigrationId, ProductVersion) "
                    "VALUES (:mid, :ver)"
                ),
                {"mid": migration_id, "ver": product_version},
            )
    logger.info("marketing_schema_created", created=True)
    return True
