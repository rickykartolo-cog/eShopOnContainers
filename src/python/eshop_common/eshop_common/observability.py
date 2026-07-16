"""Structured logging (structlog) + OpenTelemetry instrumentation.

Secrets, tokens, connection strings, and credentials must never reach the log
stream; a processor drops/redacts suspicious keys defensively.
"""

from __future__ import annotations

import logging
import uuid

import structlog

_SENSITIVE_KEY_MARKERS = (
    "password",
    "secret",
    "token",
    "authorization",
    "connectionstring",
    "connection_string",
    "apikey",
    "api_key",
)


def _redact_sensitive(_logger, _method_name, event_dict: dict) -> dict:
    for key in list(event_dict):
        if any(marker in key.lower() for marker in _SENSITIVE_KEY_MARKERS):
            event_dict[key] = "<redacted>"
    return event_dict


def configure_logging(service_name: str, level: int = logging.INFO, json_output: bool = True) -> None:
    renderer = structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _redact_sensitive,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )
    structlog.contextvars.bind_contextvars(service=service_name)
    logging.basicConfig(level=level, format="%(message)s")


def bind_request_context(request_id: str | None = None, event_id: str | None = None) -> str:
    """Bind correlation identifiers to the log context; returns the request id used."""
    request_id = request_id or str(uuid.uuid4())
    structlog.contextvars.bind_contextvars(request_id=request_id)
    if event_id:
        structlog.contextvars.bind_contextvars(event_id=event_id)
    return request_id


def configure_telemetry(app, service_name: str) -> None:
    """Set up the OpenTelemetry SDK and instrument FastAPI + HTTPX.

    Azure Monitor export is enabled through the existing
    ``ApplicationInsights__InstrumentationKey`` / connection-string configuration
    when the ``azure-monitor-opentelemetry`` package is installed.
    """
    from opentelemetry import trace
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider

    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)
