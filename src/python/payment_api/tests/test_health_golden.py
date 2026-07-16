"""Health golden parity: normalized /hc and /liveness bodies against the frozen
.NET Payment.API responses."""

import json
import subprocess
import sys
from pathlib import Path

from eshop_common.health.core import (
    HealthCheck,
    HealthCheckRegistry,
    HealthResult,
    write_health_check_ui_response,
)
from httpx import ASGITransport, AsyncClient
from payment_test_helpers import make_settings

from payment_api.app import create_app

REPO_ROOT = Path(__file__).resolve().parents[4]
NORMALIZER = REPO_ROOT / "scripts" / "contracts" / "normalize_hc.py"
HC_GOLDEN = REPO_ROOT / "contracts" / "health" / "payment.hc.golden.json"
LIVENESS_GOLDEN = REPO_ROOT / "contracts" / "health" / "payment.liveness.golden.txt"


class AlwaysHealthy(HealthCheck):
    async def check(self) -> HealthResult:
        return HealthResult.healthy()


def normalize(body: str) -> dict:
    normalized = subprocess.run(
        [sys.executable, str(NORMALIZER)], input=body, capture_output=True, text=True, check=True
    ).stdout
    return json.loads(normalized)


def payment_registry() -> HealthCheckRegistry:
    return HealthCheckRegistry().add(AlwaysHealthy("payment-rabbitmqbus-check"))  # "self" auto-registered


async def test_hc_matches_golden_shape():
    registry = payment_registry()
    response = write_health_check_ui_response(await registry.run())
    assert normalize(response.body.decode()) == json.loads(HC_GOLDEN.read_text())
    assert "application/json" in response.media_type


async def test_hc_and_liveness_endpoints():
    app = create_app(make_settings(), payment_registry())
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://payment-api") as client:
        hc = await client.get("/hc")
        assert hc.status_code == 200
        assert normalize(hc.text) == json.loads(HC_GOLDEN.read_text())

        liveness = await client.get("/liveness")
        assert liveness.status_code == 200
        assert liveness.text == LIVENESS_GOLDEN.read_text()
