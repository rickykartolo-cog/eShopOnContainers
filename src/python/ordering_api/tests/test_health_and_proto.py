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

from ordering_api.app import build_health_registry

REPO_ROOT = Path(__file__).resolve().parents[4]
NORMALIZER = REPO_ROOT / "scripts" / "contracts" / "normalize_hc.py"
HC_GOLDEN = REPO_ROOT / "contracts" / "health" / "ordering.hc.golden.json"
LIVENESS_GOLDEN = REPO_ROOT / "contracts" / "health" / "ordering.liveness.golden.txt"
PROTO = REPO_ROOT / "src" / "Services" / "Ordering" / "Ordering.API" / "Proto" / "ordering.proto"


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
        .add(AlwaysHealthy("OrderingDB-check"))
        .add(AlwaysHealthy("ordering-rabbitmqbus-check"))
    )
    response = write_health_check_ui_response(await registry.run())
    assert normalize(response.body.decode()) == json.loads(HC_GOLDEN.read_text())
    assert "application/json" in response.media_type


async def test_liveness_matches_golden(client):
    response = await client.get("/liveness")
    assert response.status_code == 200
    assert response.text == LIVENESS_GOLDEN.read_text()


def test_registry_names_match_dotnet_registration(ordering_settings):
    registry = build_health_registry(ordering_settings, engine=None)
    names = [check.name for check in registry._checks]
    assert names == ["self", "OrderingDB-check", "ordering-rabbitmqbus-check"]


def test_grpc_bindings_generated_from_frozen_proto():
    digest = hashlib.sha256(PROTO.read_bytes()).hexdigest()
    from ordering_api.grpc_gen import ordering_pb2

    descriptor_names = set(ordering_pb2.DESCRIPTOR.message_types_by_name.keys())
    assert descriptor_names == {
        "CreateOrderDraftCommand",
        "BasketItem",
        "OrderDraftDTO",
        "OrderItemDTO",
    }
    assert ordering_pb2.DESCRIPTOR.services_by_name["OrderingGrpc"] is not None
    checksum_file = Path(__file__).parent / "ordering.proto.sha256"
    assert digest == checksum_file.read_text().strip(), (
        "ordering.proto changed; the proto is frozen (master prompt §1). "
        "If this is intentional (it should not be), regenerate grpc_gen and update the checksum."
    )


def test_packaged_proto_equals_frozen_proto():
    packaged = Path(__file__).resolve().parents[1] / "ordering_api" / "contracts" / "ordering.proto"
    assert packaged.read_bytes() == PROTO.read_bytes()
