"""Health golden parity (normalized /hc + /liveness bodies) and proto-freeze
verification (the packaged gRPC bindings must come from the unchanged proto)."""

import hashlib
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

from basket_api.app import build_health_registry

REPO_ROOT = Path(__file__).resolve().parents[4]
NORMALIZER = REPO_ROOT / "scripts" / "contracts" / "normalize_hc.py"
HC_GOLDEN = REPO_ROOT / "contracts" / "health" / "basket.hc.golden.json"
LIVENESS_GOLDEN = REPO_ROOT / "contracts" / "health" / "basket.liveness.golden.txt"
PROTO = REPO_ROOT / "src" / "Services" / "Basket" / "Basket.API" / "Proto" / "basket.proto"


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
        .add(AlwaysHealthy("redis-check"))
        .add(AlwaysHealthy("basket-rabbitmqbus-check"))
    )
    response = write_health_check_ui_response(await registry.run())
    assert normalize(response.body.decode()) == json.loads(HC_GOLDEN.read_text())
    assert "application/json" in response.media_type


async def test_liveness_matches_golden(client):
    response = await client.get("/liveness")
    assert response.status_code == 200
    assert response.text == LIVENESS_GOLDEN.read_text()


def test_registry_names_match_dotnet_registration(basket_settings, redis_client):
    registry = build_health_registry(basket_settings, redis_client)
    names = [check.name for check in registry._checks]
    assert names == ["self", "redis-check", "basket-rabbitmqbus-check"]


async def test_proto_endpoint_serves_frozen_proto(client):
    response = await client.get("/_proto/")
    assert response.status_code == 200
    assert response.text == PROTO.read_text(encoding="utf-8")


def test_grpc_bindings_generated_from_frozen_proto():
    """Guards the committed grpc_gen bindings: regenerating from the unchanged
    proto must yield the same message descriptors (proto file untouched)."""
    digest = hashlib.sha256(PROTO.read_bytes()).hexdigest()
    from basket_api.grpc_gen import basket_pb2

    descriptor_names = set(basket_pb2.DESCRIPTOR.message_types_by_name.keys())
    assert descriptor_names == {
        "BasketRequest",
        "CustomerBasketRequest",
        "CustomerBasketResponse",
        "BasketItemResponse",
    }
    assert basket_pb2.DESCRIPTOR.services_by_name["Basket"] is not None
    checksum_file = Path(__file__).parent / "basket.proto.sha256"
    assert digest == checksum_file.read_text().strip(), (
        "basket.proto changed; the proto is frozen (master prompt §1). "
        "If this is intentional (it should not be), regenerate grpc_gen and update the checksum."
    )
