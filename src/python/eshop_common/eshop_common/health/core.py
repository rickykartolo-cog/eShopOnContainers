"""Health-check primitives matching ASP.NET Core health checks and the exact
``UIResponseWriter.WriteHealthCheckUIResponse`` JSON shape (golden captured from a
running netcoreapp3.1 service with AspNetCore.HealthChecks.UI.Client 3.0.0; see
``docs/golden/hc-mixed-status.json``)."""

from __future__ import annotations

import abc
import asyncio
import json
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from fastapi import Response


class HealthStatus(StrEnum):
    Healthy = "Healthy"
    Degraded = "Degraded"
    Unhealthy = "Unhealthy"


@dataclass
class HealthResult:
    status: HealthStatus
    description: str | None = None
    exception: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def healthy(cls, description: str | None = None, data: dict[str, Any] | None = None) -> HealthResult:
        return cls(HealthStatus.Healthy, description, None, data or {})

    @classmethod
    def degraded(cls, description: str | None = None, exception: str | None = None) -> HealthResult:
        return cls(HealthStatus.Degraded, description, exception)

    @classmethod
    def unhealthy(cls, description: str | None = None, exception: str | None = None) -> HealthResult:
        return cls(HealthStatus.Unhealthy, description, exception)


class HealthCheck(abc.ABC):
    def __init__(self, name: str, tags: Iterable[str] = ()) -> None:
        self.name = name
        self.tags = frozenset(tags)

    @abc.abstractmethod
    async def check(self) -> HealthResult: ...


class SelfHealthCheck(HealthCheck):
    def __init__(self, name: str = "self") -> None:
        super().__init__(name)

    async def check(self) -> HealthResult:
        return HealthResult.healthy()


@dataclass
class _Entry:
    name: str
    result: HealthResult
    duration_seconds: float


@dataclass
class HealthReport:
    entries: list[_Entry]
    total_duration_seconds: float

    @property
    def status(self) -> HealthStatus:
        worst = HealthStatus.Healthy
        for entry in self.entries:
            if entry.result.status is HealthStatus.Unhealthy:
                return HealthStatus.Unhealthy
            if entry.result.status is HealthStatus.Degraded:
                worst = HealthStatus.Degraded
        return worst


class HealthCheckRegistry:
    def __init__(self) -> None:
        self._checks: list[HealthCheck] = []
        self.add(SelfHealthCheck())

    def add(self, check: HealthCheck) -> HealthCheckRegistry:
        self._checks.append(check)
        return self

    async def run(self, predicate=None) -> HealthReport:
        checks = [c for c in self._checks if predicate is None or predicate(c)]
        started = time.perf_counter()
        entries: list[_Entry] = []
        for check in checks:
            check_started = time.perf_counter()
            try:
                result = await check.check()
            except Exception as exc:
                result = HealthResult.unhealthy(description=str(exc), exception=str(exc))
            entries.append(_Entry(check.name, result, time.perf_counter() - check_started))
        return HealthReport(entries, time.perf_counter() - started)

    async def run_liveness(self) -> HealthReport:
        return await self.run(predicate=lambda check: check.name == "self")


def format_timespan(seconds: float) -> str:
    """Format a duration like .NET ``TimeSpan`` default ("c") formatting."""
    ticks = round(seconds * 10_000_000)
    whole, fraction = divmod(ticks, 10_000_000)
    hours, remainder = divmod(whole, 3600)
    minutes, secs = divmod(remainder, 60)
    base = f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{base}.{fraction:07d}" if fraction else base


def _entry_payload(entry: _Entry) -> dict[str, Any]:
    payload: dict[str, Any] = {"data": entry.result.data}
    if entry.result.description is not None:
        payload["description"] = entry.result.description
    payload["duration"] = format_timespan(entry.duration_seconds)
    if entry.result.exception is not None:
        payload["exception"] = entry.result.exception
    payload["status"] = entry.result.status.value
    return payload


def build_ui_response_body(report: HealthReport) -> str:
    body = {
        "status": report.status.value,
        "totalDuration": format_timespan(report.total_duration_seconds),
        "entries": {entry.name: _entry_payload(entry) for entry in report.entries},
    }
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False)


def write_health_check_ui_response(report: HealthReport) -> Response:
    """Match UIResponseWriter body, content type, cache headers, and status mapping
    (Healthy/Degraded -> 200, Unhealthy -> 503)."""
    status_code = 503 if report.status is HealthStatus.Unhealthy else 200
    return Response(
        content=build_ui_response_body(report),
        status_code=status_code,
        media_type="application/json",
        headers={"Cache-Control": "no-store, no-cache", "Pragma": "no-cache"},
    )


def write_plain_response(report: HealthReport) -> Response:
    """Default ASP.NET health response used by ``/liveness``: plain status text."""
    status_code = 503 if report.status is HealthStatus.Unhealthy else 200
    return Response(
        content=report.status.value,
        status_code=status_code,
        media_type="text/plain",
        headers={"Cache-Control": "no-store, no-cache", "Pragma": "no-cache"},
    )


async def run_with_timeout(coro, timeout: float, name: str) -> HealthResult:
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except TimeoutError:
        return HealthResult.unhealthy(description=f"{name} health check timed out after {timeout}s")
