"""Health golden parity (normalized /hc + /liveness bodies), the frozen SQL
schema DDL, and serialization primitives (System.Text.Json datetime/escaping)."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from eshop_common.health.core import (
    HealthCheck,
    HealthCheckRegistry,
    HealthResult,
    write_health_check_ui_response,
)

from webhooks_api.app import build_health_registry
from webhooks_api.db import _DDL, WEBHOOKS_MIGRATIONS
from webhooks_api.serialization import stj_datetime, stj_escape

REPO_ROOT = Path(__file__).resolve().parents[4]
NORMALIZER = REPO_ROOT / "scripts" / "contracts" / "normalize_hc.py"
HC_GOLDEN = REPO_ROOT / "contracts" / "health" / "webhooks.hc.golden.json"
LIVENESS_GOLDEN = REPO_ROOT / "contracts" / "health" / "webhooks.liveness.golden.txt"
SCHEMA_GOLDEN = REPO_ROOT / "contracts" / "db" / "webhooks.sqlschema.txt"


class AlwaysHealthy(HealthCheck):
    async def check(self) -> HealthResult:
        return HealthResult.healthy()


def normalize(body: str) -> dict:
    normalized = subprocess.run(
        [sys.executable, str(NORMALIZER)], input=body, capture_output=True, text=True, check=True
    ).stdout
    return json.loads(normalized)


async def test_hc_matches_golden_shape():
    registry = HealthCheckRegistry().add(AlwaysHealthy("WebhooksApiDb-check"))
    response = write_health_check_ui_response(await registry.run())
    assert normalize(response.body.decode()) == json.loads(HC_GOLDEN.read_text())
    assert "application/json" in response.media_type


async def test_liveness_matches_golden(client):
    response = await client.get("/liveness")
    assert response.status_code == 200
    assert response.text == LIVENESS_GOLDEN.read_text()


def test_registry_names_match_dotnet_registration(webhooks_settings):
    registry = build_health_registry(webhooks_settings, engine=None)
    names = [check.name for check in registry._checks]
    # The .NET service registers exactly "self" and "WebhooksApiDb-check"
    # (no event-bus health check) — see webhooks.hc.golden.json.
    assert names == ["self", "WebhooksApiDb-check"]


def test_bootstrap_ddl_matches_frozen_schema_dump():
    golden = SCHEMA_GOLDEN.read_text()
    # Frozen columns for dbo.Subscriptions, in order, with identity on Id.
    assert "dbo.Subscriptions|Id|int|4|10|0|0|1|" in golden
    assert "dbo.Subscriptions|Type|int|4|10|0|0|0|" in golden
    assert "dbo.Subscriptions|Date|datetime2|8|27|7|0|0|" in golden
    for nullable_nvarchar_max in ("DestUrl", "Token", "UserId"):
        assert f"dbo.Subscriptions|{nullable_nvarchar_max}|nvarchar|-1|0|0|1|0|" in golden
    ddl = "\n".join(_DDL)
    assert "[Id] int NOT NULL IDENTITY" in ddl
    assert "[Date] datetime2 NOT NULL" in ddl
    for column in ("DestUrl", "Token", "UserId"):
        assert f"[{column}] nvarchar(max) NULL" in ddl
    assert "CONSTRAINT [PK_Subscriptions] PRIMARY KEY ([Id])" in ddl
    assert WEBHOOKS_MIGRATIONS == [("20190118091148_Initial", "2.2.1-servicing-10028")]
    # No extra tables: the frozen dump has no outbox/inbox or FKs/sequences.
    assert "FOREIGN KEY" not in ddl
    assert "SEQUENCE" not in ddl


def test_stj_datetime_formats():
    utc = datetime(2020, 1, 2, 3, 4, 5, 678000, tzinfo=UTC)
    assert stj_datetime(utc) == "2020-01-02T03:04:05.678Z"
    naive = datetime(2020, 1, 2, 3, 4, 5)  # e.g. read back from datetime2
    assert stj_datetime(naive) == "2020-01-02T03:04:05"
    micro = datetime(2020, 1, 2, 3, 4, 5, 100, tzinfo=UTC)
    assert stj_datetime(micro) == "2020-01-02T03:04:05.0001Z"


def test_stj_escaping_matches_default_encoder():
    assert stj_escape("plain") == "plain"
    assert stj_escape('say "hi"') == "say \\u0022hi\\u0022"
    assert stj_escape("<b>&'</b>") == "\\u003Cb\\u003E\\u0026\\u0027\\u003C/b\\u003E"
    assert stj_escape("a+b") == "a\\u002Bb"
    assert stj_escape("café") == "caf\\u00E9"
