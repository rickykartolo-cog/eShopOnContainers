"""Configuration loading that accepts the existing eShopOnContainers env-var names.

The historical .NET configuration is case-insensitive: compose files set
``identityUrl`` while some code reads ``IdentityUrl``. Lookups here are
case-insensitive to preserve that behavior. Missing required settings fail fast
with a redacted, actionable error that never echoes secret values.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

_SECRET_MARKERS = ("password", "secret", "key", "token", "connectionstring", "connection_string")


class ConfigurationError(RuntimeError):
    """Raised when required configuration is missing or invalid."""


def redact(name: str, value: str | None) -> str:
    if value is None:
        return "<missing>"
    if any(marker in name.lower() for marker in _SECRET_MARKERS):
        return "<redacted>"
    return value


class Settings:
    """Case-insensitive view over environment variables (or any mapping)."""

    def __init__(self, source: Mapping[str, str] | None = None) -> None:
        raw = dict(os.environ if source is None else source)
        self._values: dict[str, str] = {}
        self._original_names: dict[str, str] = {}
        for name, value in raw.items():
            self._values[name.lower()] = value
            self._original_names[name.lower()] = name

    def get(self, name: str, default: str | None = None) -> str | None:
        return self._values.get(name.lower(), default)

    def require(self, name: str, hint: str | None = None) -> str:
        value = self._values.get(name.lower())
        if value is None or value == "":
            message = f"Missing required configuration '{name}'."
            if hint:
                message += f" {hint}"
            raise ConfigurationError(message)
        return value

    def get_bool(self, name: str, default: bool = False) -> bool:
        value = self.get(name)
        if value is None or value == "":
            return default
        return value.strip().lower() in ("true", "1", "yes")

    def get_int(self, name: str, default: int | None = None) -> int | None:
        value = self.get(name)
        if value is None or value == "":
            return default
        try:
            return int(value)
        except ValueError as exc:
            raise ConfigurationError(
                f"Configuration '{name}' must be an integer, got {redact(name, value)!r}."
            ) from exc

    def require_all(self, names_with_hints: Mapping[str, str | None]) -> dict[str, str]:
        """Validate a batch of required settings, reporting every missing name at once."""
        missing = [name for name in names_with_hints if not self.get(name)]
        if missing:
            details = "; ".join(
                f"'{name}'" + (f" ({names_with_hints[name]})" if names_with_hints[name] else "")
                for name in missing
            )
            raise ConfigurationError(f"Missing required configuration: {details}")
        return {name: self.require(name) for name in names_with_hints}

    def describe(self) -> dict[str, Any]:
        """Redacted snapshot suitable for logging (never includes secret values)."""
        return {
            self._original_names[key]: redact(key, value)
            for key, value in sorted(self._values.items())
        }


class ServiceSettings:
    """Common settings shared by every migrated service.

    Uses the exact environment-variable interface of the existing compose files:
    ``ConnectionString``, ``EventBusConnection``, ``EventBusUserName``,
    ``EventBusPassword``, ``AzureServiceBusEnabled``, ``SubscriptionClientName``,
    ``identityUrl``/``IdentityUrl``, ``IdentityUrlExternal``, ``PATH_BASE``,
    ``PORT`` and ``GRPC_PORT``.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings()

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def connection_string(self) -> str:
        return self._settings.require(
            "ConnectionString",
            hint="Set the service database/redis connection string as in docker-compose.override.yml.",
        )

    @property
    def event_bus_connection(self) -> str:
        return self._settings.require(
            "EventBusConnection",
            hint="Set the RabbitMQ host name or the Azure Service Bus connection string.",
        )

    @property
    def event_bus_username(self) -> str | None:
        return self._settings.get("EventBusUserName") or None

    @property
    def event_bus_password(self) -> str | None:
        return self._settings.get("EventBusPassword") or None

    @property
    def event_bus_retry_count(self) -> int:
        return self._settings.get_int("EventBusRetryCount", 5) or 5

    @property
    def azure_service_bus_enabled(self) -> bool:
        return self._settings.get_bool("AzureServiceBusEnabled", False)

    @property
    def subscription_client_name(self) -> str:
        return self._settings.require(
            "SubscriptionClientName",
            hint="Set the queue/subscription name used by this service on the event bus.",
        )

    @property
    def identity_url(self) -> str:
        # Historical casing differs between services (identityUrl vs IdentityUrl);
        # lookups are case-insensitive so both resolve.
        return self._settings.require(
            "identityUrl",
            hint="Set the internal identity service URL (e.g. http://identity-api).",
        )

    @property
    def identity_url_external(self) -> str | None:
        return self._settings.get("IdentityUrlExternal")

    @property
    def path_base(self) -> str | None:
        return self._settings.get("PATH_BASE")

    @property
    def http_port(self) -> int:
        return self._settings.get_int("PORT", 80) or 80

    @property
    def grpc_port(self) -> int:
        return self._settings.get_int("GRPC_PORT", 81) or 81
