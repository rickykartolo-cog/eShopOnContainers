import json
import re
from pathlib import Path

from eshop_common.health.core import (
    HealthCheck,
    HealthCheckRegistry,
    HealthResult,
    HealthStatus,
    build_ui_response_body,
    format_timespan,
    write_health_check_ui_response,
    write_plain_response,
)

GOLDEN = Path(__file__).parents[2] / "docs" / "golden" / "hc-mixed-status.json"

DURATION_RE = re.compile(r"^\d{2}:\d{2}:\d{2}(\.\d{7})?$")


class StubCheck(HealthCheck):
    def __init__(self, name: str, result: HealthResult) -> None:
        super().__init__(name)
        self._result = result

    async def check(self) -> HealthResult:
        return self._result


def registry_matching_golden() -> HealthCheckRegistry:
    registry = HealthCheckRegistry()
    registry.add(StubCheck("dep-degraded", HealthResult.degraded("slow dependency", "degraded-exc")))
    registry.add(StubCheck("dep-unhealthy", HealthResult.unhealthy("broken dependency", "boom")))
    registry.add(
        StubCheck("dep-data", HealthResult.healthy("with data", {"key1": "value1", "num": 42}))
    )
    return registry


def normalize(payload: dict) -> dict:
    payload = json.loads(json.dumps(payload))
    payload["totalDuration"] = "<duration>"
    for entry in payload["entries"].values():
        entry["duration"] = "<duration>"
    return payload


async def test_hc_body_matches_golden_dotnet_uiresponsewriter_shape():
    golden = json.loads(GOLDEN.read_text())
    report = await registry_matching_golden().run()
    body = json.loads(build_ui_response_body(report))
    assert normalize(body) == normalize(golden)
    # exact key order matters for byte-parity with UIResponseWriter
    assert list(body) == ["status", "totalDuration", "entries"]
    for entry in body["entries"].values():
        expected = [k for k in ("data", "description", "duration", "exception", "status") if k in entry]
        assert list(entry) == expected
    assert DURATION_RE.match(body["totalDuration"])


async def test_status_codes_and_headers_match_dotnet():
    unhealthy = write_health_check_ui_response(await registry_matching_golden().run())
    assert unhealthy.status_code == 503
    assert unhealthy.media_type == "application/json"
    assert unhealthy.headers["Cache-Control"] == "no-store, no-cache"
    assert unhealthy.headers["Pragma"] == "no-cache"

    healthy_registry = HealthCheckRegistry()
    healthy = write_health_check_ui_response(await healthy_registry.run())
    assert healthy.status_code == 200

    degraded_registry = HealthCheckRegistry()
    degraded_registry.add(StubCheck("dep", HealthResult.degraded("slow")))
    degraded = write_health_check_ui_response(await degraded_registry.run())
    assert degraded.status_code == 200
    assert json.loads(degraded.body)["status"] == "Degraded"


async def test_liveness_is_self_only_plain_text():
    registry = registry_matching_golden()
    report = await registry.run_liveness()
    assert [entry.name for entry in report.entries] == ["self"]
    response = write_plain_response(report)
    assert response.status_code == 200
    assert response.body == b"Healthy"
    assert response.media_type == "text/plain"


async def test_check_exception_becomes_unhealthy_entry():
    class Exploding(HealthCheck):
        async def check(self) -> HealthResult:
            raise RuntimeError("connection refused")

    registry = HealthCheckRegistry()
    registry.add(Exploding("dep"))
    report = await registry.run()
    assert report.status is HealthStatus.Unhealthy
    entry = next(e for e in report.entries if e.name == "dep")
    assert entry.result.status is HealthStatus.Unhealthy
    assert "connection refused" in (entry.result.description or "")


def test_format_timespan_matches_dotnet_timespan_c_format():
    assert format_timespan(0.0033158) == "00:00:00.0033158"
    assert format_timespan(0) == "00:00:00"
    assert format_timespan(1.5) == "00:00:01.5000000"
    assert format_timespan(3661.0000001) == "01:01:01.0000001"
