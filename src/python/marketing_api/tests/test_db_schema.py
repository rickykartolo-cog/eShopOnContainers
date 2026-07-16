"""SQL write-model parity with the frozen schema dump
(`contracts/db/marketing.sqlschema.txt`): table/column names, nullability,
FK/cascade, HiLo sequences (increment 10), and EF migrations-history preservation."""

from pathlib import Path

from sqlalchemy import inspect as sqla_inspect

from marketing_api.db import _DDL, MARKETING_MIGRATIONS
from marketing_api.models import (
    CAMPAIGN_HILO,
    HILO_BLOCK_SIZE,
    RULE_HILO,
    USER_LOCATION_RULE_TYPE,
    Base,
    Campaign,
    Rule,
    UserLocationRule,
)

SCHEMA_DUMP = Path(__file__).resolve().parents[4] / "contracts" / "db" / "marketing.sqlschema.txt"


def frozen_columns() -> dict[str, list[tuple[str, bool]]]:
    tables: dict[str, list[tuple[str, bool]]] = {}
    for line in SCHEMA_DUMP.read_text().splitlines():
        parts = line.split("|")
        if len(parts) == 9 and parts[0].startswith("dbo.") and not parts[0].endswith("__EFMigrationsHistory"):
            tables.setdefault(parts[0].removeprefix("dbo."), []).append((parts[1], parts[6] == "1"))
    return tables


def test_model_columns_match_frozen_dump():
    frozen = frozen_columns()
    for table_name, columns in frozen.items():
        model_table = Base.metadata.tables[table_name]
        model_columns = {column.name: column.nullable for column in model_table.columns}
        assert model_columns == dict(columns), table_name


def test_foreign_key_and_cascade():
    rule = Base.metadata.tables["Rule"]
    fk = next(iter(rule.foreign_keys))
    assert fk.column.table.name == "Campaign"
    assert fk.ondelete == "CASCADE"


def test_hilo_sequences_match_frozen_dump():
    assert (CAMPAIGN_HILO.name, CAMPAIGN_HILO.start, CAMPAIGN_HILO.increment) == ("campaign_hilo", 1, 10)
    assert (RULE_HILO.name, RULE_HILO.start, RULE_HILO.increment) == ("rule_hilo", 1, 10)
    assert HILO_BLOCK_SIZE == 10


def test_user_location_rule_discriminator():
    assert USER_LOCATION_RULE_TYPE == 3
    mapper = sqla_inspect(UserLocationRule)
    assert mapper.polymorphic_identity == 3
    assert sqla_inspect(Rule).polymorphic_on.name == "RuleTypeId"


def test_bootstrap_ddl_matches_frozen_objects():
    ddl = "\n".join(_DDL)
    for fragment in (
        "CREATE TABLE [Campaign]",
        "CREATE TABLE [Rule]",
        "CREATE TABLE [__EFMigrationsHistory]",
        "CREATE SEQUENCE [campaign_hilo] START WITH 1 INCREMENT BY 10",
        "CREATE SEQUENCE [rule_hilo] START WITH 1 INCREMENT BY 10",
        "CONSTRAINT [PK_Campaign] PRIMARY KEY ([Id])",
        "CONSTRAINT [PK_Rule] PRIMARY KEY ([Id])",
        "CONSTRAINT [FK_Rule_Campaign_CampaignId] FOREIGN KEY ([CampaignId])",
        "ON DELETE CASCADE",
        "CREATE INDEX [IX_Rule_CampaignId] ON [Rule] ([CampaignId])",
    ):
        assert fragment in ddl, fragment
    assert [migration for migration, _ in MARKETING_MIGRATIONS] == [
        "20170615163431_Init",
        "20170629102516_added-campaign-details",
    ]


def test_campaign_rule_relationship_cascade_delete_orphan():
    relationship = sqla_inspect(Campaign).relationships["Rules"]
    assert relationship.cascade.delete
