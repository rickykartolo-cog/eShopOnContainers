"""Integration-event base type with Newtonsoft.Json-compatible serialization.

Golden output captured from Newtonsoft.Json 12.0.3 on netcoreapp3.1
(see ``docs/golden/newtonsoft-product-price-changed.jsonl``):

- PascalCase property names (default contract resolver, ``[JsonProperty]``)
- derived-class properties are written first, base ``Id``/``CreationDate`` last
- lowercase GUID text
- UTC ``DateTime`` as ISO-8601 with up to 7 fractional digits, trailing zeros
  trimmed and the fraction omitted when zero (``yyyy-MM-ddTHH:mm:ss.FFFFFFFK``)
- ``decimal`` values keep their scale (``12.50m`` -> ``12.50``) and integral
  decimals gain one decimal place (``10m`` -> ``10.0``)
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(UTC)


def newtonsoft_datetime(value: datetime) -> str:
    """Format a datetime the way Newtonsoft.Json serializes UTC ``DateTime``."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(UTC)
    base = value.strftime("%Y-%m-%dT%H:%M:%S")
    fraction = f"{value.microsecond:06d}0".rstrip("0")
    return f"{base}.{fraction}Z" if fraction else f"{base}Z"


_NEWTONSOFT_DT = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,7}))?(Z|[+-]\d{2}:\d{2})?$")


def parse_newtonsoft_datetime(text: str) -> datetime:
    match = _NEWTONSOFT_DT.match(text)
    if not match:
        raise ValueError(f"Not an ISO-8601 datetime: {text!r}")
    seconds, fraction, offset = match.groups()
    microseconds = int((fraction or "0").ljust(6, "0")[:6])
    if offset in (None, "Z"):
        return datetime.fromisoformat(seconds).replace(microsecond=microseconds, tzinfo=UTC)
    return datetime.fromisoformat(f"{seconds}{offset}").replace(microsecond=microseconds).astimezone(UTC)


def dumps_newtonsoft(value: Any) -> str:
    """JSON writer matching ``JsonConvert.SerializeObject`` output for the types
    used by integration events (objects, arrays, strings, numbers, decimals,
    GUIDs, UTC datetimes, booleans, null)."""
    parts: list[str] = []
    _write(value, parts)
    return "".join(parts)


def _write(value: Any, parts: list[str]) -> None:
    if value is None:
        parts.append("null")
    elif isinstance(value, BaseModel):
        _write(_model_items(value), parts)
    elif isinstance(value, bool):
        parts.append("true" if value else "false")
    elif isinstance(value, str):
        parts.append(json.dumps(value, ensure_ascii=False))
    elif isinstance(value, Decimal):
        text = format(value, "f")
        parts.append(text if "." in text else f"{text}.0")
    elif isinstance(value, int | float):
        parts.append(json.dumps(value))
    elif isinstance(value, uuid.UUID):
        parts.append(f'"{value}"')
    elif isinstance(value, datetime):
        parts.append(f'"{newtonsoft_datetime(value)}"')
    elif isinstance(value, dict):
        parts.append("{")
        for index, (key, item) in enumerate(value.items()):
            if index:
                parts.append(",")
            parts.append(json.dumps(str(key), ensure_ascii=False))
            parts.append(":")
            _write(item, parts)
        parts.append("}")
    elif isinstance(value, list | tuple):
        parts.append("[")
        for index, item in enumerate(value):
            if index:
                parts.append(",")
            _write(item, parts)
        parts.append("]")
    else:
        raise TypeError(f"Cannot serialize {type(value)!r} to Newtonsoft-compatible JSON")


def _model_items(model: BaseModel) -> dict[str, Any]:
    """Field name/value pairs in Newtonsoft order: derived-class properties first,
    base-class (``IntegrationEvent``) properties last."""
    fields = type(model).model_fields
    base_names = [name for name in fields if name in IntegrationEvent.model_fields]
    derived_names = [name for name in fields if name not in IntegrationEvent.model_fields]
    ordered = derived_names + base_names if isinstance(model, IntegrationEvent) else list(fields)
    return {
        (fields[name].serialization_alias or fields[name].alias or name): getattr(model, name)
        for name in ordered
    }


class IntegrationEvent(BaseModel):
    """Base integration event mirroring the .NET ``IntegrationEvent`` contract."""

    model_config = ConfigDict(populate_by_name=True)

    #: Suffix stripped for the Azure Service Bus Label/Subject.
    INTEGRATION_EVENT_SUFFIX: ClassVar[str] = "IntegrationEvent"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, alias="Id")
    creation_date: datetime = Field(default_factory=_utc_now, alias="CreationDate")

    @classmethod
    def event_name(cls) -> str:
        """The RabbitMQ routing key: the event class name."""
        return cls.__name__

    @classmethod
    def service_bus_label(cls) -> str:
        """Azure Service Bus Label/Subject: class name without the ``IntegrationEvent`` suffix."""
        return cls.__name__.replace(cls.INTEGRATION_EVENT_SUFFIX, "")

    def to_json(self) -> str:
        """Serialize matching ``JsonConvert.SerializeObject`` output exactly."""
        return dumps_newtonsoft(self)

    @classmethod
    def from_json(cls, payload: str | bytes):
        data = json.loads(payload, parse_float=Decimal)
        if isinstance(data.get("CreationDate"), str):
            data["CreationDate"] = parse_newtonsoft_datetime(data["CreationDate"])
        return cls.model_validate(data)
