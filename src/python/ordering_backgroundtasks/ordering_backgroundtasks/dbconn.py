"""ADO.NET -> SQLAlchemy connection-string conversion (ODBC Driver 18)."""

from __future__ import annotations

from urllib.parse import quote_plus


def ado_to_sqlalchemy_url(connection_string: str) -> str:
    parts: dict[str, str] = {}
    for chunk in connection_string.split(";"):
        if "=" in chunk:
            key, _, value = chunk.partition("=")
            parts[key.strip().lower()] = value.strip()
    server = parts.get("server", "localhost")
    port = "1433"
    if "," in server:
        server, port = server.split(",", 1)
    if server.lower().startswith("tcp:"):
        server = server[4:]
    odbc = (
        "Driver={ODBC Driver 18 for SQL Server};"
        f"Server=tcp:{server},{port};"
        f"Database={parts.get('database', parts.get('initial catalog', ''))};"
        f"Uid={parts.get('user id', parts.get('uid', ''))};"
        f"Pwd={parts.get('password', parts.get('pwd', ''))};"
        "Encrypt=Optional;TrustServerCertificate=yes;"
    )
    return f"mssql+aioodbc:///?odbc_connect={quote_plus(odbc)}"
