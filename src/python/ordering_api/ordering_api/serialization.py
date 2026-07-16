"""HTTP response serialization matching ASP.NET Core 3.1 + AddNewtonsoftJson:
camelCase/lowercase property names as declared on the .NET view models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from eshop_common.events import dumps_newtonsoft
from fastapi import Response


def unspecified_datetime(value: datetime) -> str:
    """Newtonsoft serialization of a ``DateTimeKind.Unspecified`` value (as read
    from a SQL Server ``datetime2`` column): ISO-8601 without an offset suffix."""
    base = value.strftime("%Y-%m-%dT%H:%M:%S")
    fraction = f"{value.microsecond:06d}0".rstrip("0")
    return f"{base}.{fraction}" if fraction else base


def json_response(payload: Any, status_code: int = 200) -> Response:
    return Response(
        content=dumps_newtonsoft(payload),
        status_code=status_code,
        media_type="application/json; charset=utf-8",
    )
