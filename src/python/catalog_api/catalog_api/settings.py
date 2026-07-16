"""Catalog settings honoring the exact compose environment-variable interface
(`ConnectionString`, `PicBaseUrl`, `AzureStorageEnabled`, `UseCustomizationData`,
`EventBusConnection`, `SubscriptionClientName`, `PORT`, `GRPC_PORT`, `PATH_BASE`)."""

from __future__ import annotations

from pathlib import Path

from eshop_common.config import ServiceSettings, Settings


class CatalogSettings(ServiceSettings):
    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings)

    @property
    def pic_base_url(self) -> str:
        return self.settings.get("PicBaseUrl") or ""

    @property
    def azure_storage_enabled(self) -> bool:
        return self.settings.get_bool("AzureStorageEnabled", False)

    @property
    def use_customization_data(self) -> bool:
        return self.settings.get_bool("UseCustomizationData", False)

    @property
    def pics_path(self) -> Path:
        return Path(self.settings.get("PICS_PATH") or Path(__file__).resolve().parent.parent / "Pics")

    @property
    def proto_path(self) -> Path | None:
        value = self.settings.get("CATALOG_PROTO_PATH")
        return Path(value) if value else None

    @property
    def setup_path(self) -> Path:
        return Path(self.settings.get("SETUP_PATH") or Path(__file__).resolve().parent.parent / "Setup")

    def sqlalchemy_url(self) -> str:
        """Build the aioodbc URL from the unchanged ADO.NET-style ConnectionString."""
        return ado_to_sqlalchemy_url(self.connection_string)


def ado_to_sqlalchemy_url(connection_string: str) -> str:
    """Convert an ADO.NET SQL Server connection string (compose interface) into a
    ``mssql+aioodbc`` URL using ODBC Driver 18."""
    from urllib.parse import quote_plus

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
