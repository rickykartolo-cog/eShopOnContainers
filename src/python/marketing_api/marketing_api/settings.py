"""Marketing settings honoring the exact compose environment-variable interface
(`ConnectionString`, `MongoConnectionString`, `MongoDatabase`, `PicBaseUrl`,
`AzureStorageEnabled`, `CampaignDetailFunctionUri`, `EventBusConnection`,
`SubscriptionClientName`, `identityUrl`, `UseLoadTest`, `PORT`, `PATH_BASE`)."""

from __future__ import annotations

from pathlib import Path

from eshop_common.config import ServiceSettings, Settings


class MarketingSettings(ServiceSettings):
    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings)

    @property
    def mongo_connection_string(self) -> str:
        return self.settings.require(
            "MongoConnectionString",
            hint="Set the MongoDB connection string as in docker-compose.override.yml.",
        )

    @property
    def mongo_database(self) -> str:
        return self.settings.get("MongoDatabase") or "MarketingDb"

    @property
    def pic_base_url(self) -> str:
        return self.settings.get("PicBaseUrl") or ""

    @property
    def azure_storage_enabled(self) -> bool:
        return self.settings.get_bool("AzureStorageEnabled", False)

    @property
    def campaign_detail_function_uri(self) -> str:
        return self.settings.get("CampaignDetailFunctionUri") or ""

    @property
    def use_load_test(self) -> bool:
        return self.settings.get_bool("UseLoadTest", False)

    @property
    def pics_path(self) -> Path:
        return Path(self.settings.get("PICS_PATH") or Path(__file__).resolve().parent.parent / "Pics")

    def sqlalchemy_url(self) -> str:
        """Build the aioodbc URL from the unchanged ADO.NET-style ConnectionString."""
        return ado_to_sqlalchemy_url(self.connection_string)


def parse_ado_connection_string(connection_string: str) -> dict[str, str]:
    parts: dict[str, str] = {}
    for chunk in connection_string.split(";"):
        if "=" in chunk:
            key, _, value = chunk.partition("=")
            parts[key.strip().lower()] = value.strip()
    return parts


def ado_to_sqlalchemy_url(connection_string: str) -> str:
    """Convert an ADO.NET SQL Server connection string (compose interface) into a
    ``mssql+aioodbc`` URL using ODBC Driver 18."""
    from urllib.parse import quote_plus

    parts = parse_ado_connection_string(connection_string)
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
