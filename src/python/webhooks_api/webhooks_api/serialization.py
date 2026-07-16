"""HTTP response serialization matching ASP.NET Core 3.1 defaults
(System.Text.Json, unlike Catalog which opts into Newtonsoft): camelCase
property names, ISO-8601 datetimes with trailing-zero-trimmed fractions and a
``Z`` suffix only for UTC kinds, and the default ``JavaScriptEncoder`` escaping
(non-ASCII plus HTML-sensitive characters as ``\\uXXXX``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import Response

from webhooks_api.models import WebhookSubscription

_SAFE = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    " !#$%()*,-./:;=?@[]^_{|}~"
)


def stj_escape(value: str) -> str:
    """String escaping of System.Text.Json's default ``JavaScriptEncoder``."""
    parts: list[str] = []
    for char in value:
        if char in _SAFE:
            parts.append(char)
        elif char == "\\":
            parts.append("\\\\")
        elif char == '"':
            parts.append("\\u0022")
        elif char == "\n":
            parts.append("\\n")
        elif char == "\r":
            parts.append("\\r")
        elif char == "\t":
            parts.append("\\t")
        elif char == "\b":
            parts.append("\\b")
        elif char == "\f":
            parts.append("\\f")
        else:
            code = ord(char)
            if code > 0xFFFF:
                # Encode as a UTF-16 surrogate pair, like .NET.
                code -= 0x10000
                parts.append(f"\\u{0xD800 + (code >> 10):04X}\\u{0xDC00 + (code & 0x3FF):04X}")
            else:
                parts.append(f"\\u{code:04X}")
    return "".join(parts)


def stj_datetime(value: datetime) -> str:
    """Format a datetime the way System.Text.Json serializes ``DateTime``:
    fraction trimmed of trailing zeros (omitted when zero), ``Z`` only when the
    value is UTC-aware (Kind.Utc); naive values (Kind.Unspecified — e.g. read
    back from a SQL ``datetime2`` column) carry no offset."""
    base = value.strftime("%Y-%m-%dT%H:%M:%S")
    fraction = f"{value.microsecond:06d}0".rstrip("0")
    text = f"{base}.{fraction}" if fraction else base
    if value.tzinfo is not None and value.utcoffset() is not None:
        offset = value.utcoffset()
        if offset is not None and offset.total_seconds() == 0:
            return f"{text}Z"
        return f"{text}{value.strftime('%z')[:3]}:{value.strftime('%z')[3:]}"
    return text


def stj_dumps(value: Any) -> str:
    parts: list[str] = []
    _write(value, parts)
    return "".join(parts)


def _write(value: Any, parts: list[str]) -> None:
    if value is None:
        parts.append("null")
    elif isinstance(value, bool):
        parts.append("true" if value else "false")
    elif isinstance(value, str):
        parts.append(f'"{stj_escape(value)}"')
    elif isinstance(value, int | float):
        import json

        parts.append(json.dumps(value))
    elif isinstance(value, datetime):
        parts.append(f'"{stj_datetime(value)}"')
    elif isinstance(value, dict):
        parts.append("{")
        for index, (key, item) in enumerate(value.items()):
            if index:
                parts.append(",")
            parts.append(f'"{stj_escape(str(key))}":')
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
        raise TypeError(f"Cannot serialize {type(value)!r} to System.Text.Json-compatible JSON")


def subscription_payload(subscription: WebhookSubscription) -> dict[str, Any]:
    """CamelCase ``WebhookSubscription`` shape, field-for-field with the .NET
    model (``type`` stays the numeric enum value, as System.Text.Json defaults)."""
    return {
        "id": subscription.Id,
        "type": subscription.Type,
        "date": subscription.Date,
        "destUrl": subscription.DestUrl,
        "token": subscription.Token,
        "userId": subscription.UserId,
    }


def json_response(payload: Any, status_code: int = 200, headers: dict[str, str] | None = None) -> Response:
    return Response(
        content=stj_dumps(payload),
        status_code=status_code,
        media_type="application/json; charset=utf-8",
        headers=headers,
    )


def text_response(payload: str, status_code: int) -> Response:
    """ASP.NET's ``StringOutputFormatter``: bare string results are text/plain."""
    return Response(content=payload, status_code=status_code, media_type="text/plain; charset=utf-8")
