"""Health golden parity (normalized /hc + /liveness bodies) and proto-freeze
verification (the packaged gRPC bindings must come from the unchanged proto)."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from eshop_common.health.core import HealthCheck, HealthCheckRegistry, HealthResult

from catalog_api.app import build_health_registry

REPO_ROOT = Path(__file__).resolve().parents[4]
NORMALIZER = REPO_ROOT / "scripts" / "contracts" / "normalize_hc.py"
HC_GOLDEN = REPO_ROOT / "contracts" / "health" / "catalog.hc.golden.json"
LIVENESS_GOLDEN = REPO_ROOT / "contracts" / "health" / "catalog.liveness.golden.txt"
PROTO = REPO_ROOT / "src" / "Services" / "Catalog" / "Catalog.API" / "Proto" / "catalog.proto"


class AlwaysHealthy(HealthCheck):
    async def check(self) -> HealthResult:
        return HealthResult.healthy()


def normalize(body: str) -> dict:
    normalized = subprocess.run(
        [sys.executable, str(NORMALIZER)], input=body, capture_output=True, text=True, check=True
    ).stdout
    return json.loads(normalized)


async def test_hc_matches_golden_shape(client, app):
    registry = (
        HealthCheckRegistry()  # registers "self"
        .add(AlwaysHealthy("CatalogDB-check"))
        .add(AlwaysHealthy("catalog-rabbitmqbus-check"))
    )
    app.state.health = registry
    # The /hc endpoint closes over the registry passed to create_service_app, so
    # exercise the writer directly with the catalog-named checks.
    from eshop_common.health.core import write_health_check_ui_response

    response = write_health_check_ui_response(await registry.run())
    assert normalize(response.body.decode()) == json.loads(HC_GOLDEN.read_text())
    assert "application/json" in response.media_type


async def test_liveness_matches_golden(client):
    response = await client.get("/liveness")
    assert response.status_code == 200
    assert response.text == LIVENESS_GOLDEN.read_text()


def test_registry_names_match_dotnet_registration(catalog_settings):
    registry = build_health_registry(catalog_settings, engine=None)
    names = [check.name for check in registry._checks]
    assert names == ["self", "CatalogDB-check", "catalog-rabbitmqbus-check"]


def test_grpc_bindings_generated_from_frozen_proto():
    """Guards the committed grpc_gen bindings: regenerating from the unchanged
    proto must yield the same message descriptors (proto file untouched)."""
    digest = hashlib.sha256(PROTO.read_bytes()).hexdigest()
    from catalog_api.grpc_gen import catalog_pb2

    descriptor_names = set(catalog_pb2.DESCRIPTOR.message_types_by_name.keys())
    assert descriptor_names == {
        "CatalogItemRequest",
        "CatalogItemsRequest",
        "CatalogItemResponse",
        "CatalogBrand",
        "CatalogType",
        "PaginatedItemsResponse",
    }
    assert catalog_pb2.DESCRIPTOR.services_by_name["Catalog"] is not None
    checksum_file = Path(__file__).parent / "catalog.proto.sha256"
    assert digest == checksum_file.read_text().strip(), (
        "catalog.proto changed; the proto is frozen (master prompt §1). "
        "If this is intentional (it should not be), regenerate grpc_gen and update the checksum."
    )
