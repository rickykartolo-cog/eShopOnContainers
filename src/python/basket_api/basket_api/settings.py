"""Basket settings honoring the exact compose environment-variable interface
(`ConnectionString` = Redis endpoint, `identityUrl`, `IdentityUrlExternal`,
`EventBusConnection`, `SubscriptionClientName`, `PORT`, `GRPC_PORT`, `PATH_BASE`)."""

from __future__ import annotations

from pathlib import Path

from eshop_common.config import ServiceSettings, Settings


class BasketSettings(ServiceSettings):
    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings)

    @property
    def proto_path(self) -> Path | None:
        value = self.settings.get("BASKET_PROTO_PATH")
        return Path(value) if value else None

    def redis_url(self) -> str:
        return stackexchange_to_redis_url(self.connection_string)


def stackexchange_to_redis_url(connection_string: str) -> str:
    """Convert a StackExchange.Redis configuration string (compose interface,
    e.g. ``basketdata`` or ``host:6380,password=...,ssl=True``) into a redis-py URL."""
    endpoint = "localhost:6379"
    password = None
    ssl = False
    for index, chunk in enumerate(connection_string.split(",")):
        chunk = chunk.strip()
        if index == 0 and "=" not in chunk:
            endpoint = chunk
            continue
        key, _, value = chunk.partition("=")
        key = key.strip().lower()
        if key == "password":
            password = value
        elif key == "ssl":
            ssl = value.strip().lower() in ("true", "1", "yes")
    if ":" not in endpoint:
        endpoint = f"{endpoint}:6379"
    scheme = "rediss" if ssl else "redis"
    auth = f":{password}@" if password else ""
    return f"{scheme}://{auth}{endpoint}/0"
