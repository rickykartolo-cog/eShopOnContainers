"""Health golden parity: normalized /hc body and /liveness body must match the
frozen goldens, and the registered check names must match the .NET registration."""

import json
import subprocess
import sys
from pathlib import Path

from eshop_common.health.core import HealthCheck, HealthCheckRegistry, HealthResult, write_health_check_ui_response

REPO_ROOT = Path(__file__).resolve().parents[4]
NORMALIZER = REPO_ROOT / "scripts" / "contracts" / "normalize_hc.py"
HC_GOLDEN = REPO_ROOT / "contracts" / "health" / "marketing.hc.golden.json"
LIVENESS_GOLDEN = REPO_ROOT / "contracts" / "health" / "marketing.liveness.golden.txt"


class AlwaysHealthy(HealthCheck):
    async def check(self) -> HealthResult:
        return HealthResult.healthy()


def normalize(body: str) -> dict:
    normalized = subprocess.run(
        [sys.executable, str(NORMALIZER)], input=body, capture_output=True, text=True, check=True
    ).stdout
    return json.loads(normalized)


async def test_hc_matches_golden_shape():
    registry = (
        HealthCheckRegistry()  # registers "self"
        .add(AlwaysHealthy("MarketingDB-check"))
        .add(AlwaysHealthy("MarketingDB-mongodb-check"))
        .add(AlwaysHealthy("marketing-rabbitmqbus-check"))
    )
    response = write_health_check_ui_response(await registry.run())
    assert normalize(response.body.decode()) == json.loads(HC_GOLDEN.read_text())
    assert "application/json" in response.media_type


async def test_liveness_matches_golden(client):
    response = await client.get("/liveness")
    assert response.status_code == 200
    assert response.text == LIVENESS_GOLDEN.read_text()


def test_registry_names_match_dotnet_registration(marketing_settings):
    from marketing_api.app import build_health_registry

    registry = build_health_registry(marketing_settings, engine=None, mongo_client=None)
    names = [check.name for check in registry._checks]
    assert names == ["self", "MarketingDB-check", "MarketingDB-mongodb-check", "marketing-rabbitmqbus-check"]
