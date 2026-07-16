import pytest

from eshop_common.config import ConfigurationError, ServiceSettings, Settings


def make_settings(**values: str) -> Settings:
    return Settings(values)


def test_case_insensitive_lookup_matches_historical_casing():
    settings = make_settings(identityUrl="http://identity-api")
    assert settings.get("IdentityUrl") == "http://identity-api"
    assert settings.get("identityurl") == "http://identity-api"
    assert settings.get("IDENTITYURL") == "http://identity-api"


def test_service_settings_reads_compose_variable_names():
    service = ServiceSettings(
        make_settings(
            ConnectionString="Server=sqldata;Database=CatalogDb;User Id=sa;Password=Pass@word",
            EventBusConnection="rabbitmq",
            EventBusUserName="",
            EventBusPassword="",
            AzureServiceBusEnabled="False",
            SubscriptionClientName="Catalog",
            identityUrl="http://identity-api",
            IdentityUrlExternal="http://localhost:5105",
            PATH_BASE="/catalog-api",
            PORT="80",
            GRPC_PORT="81",
        )
    )
    assert service.connection_string.startswith("Server=sqldata")
    assert service.event_bus_connection == "rabbitmq"
    assert service.event_bus_username is None
    assert service.azure_service_bus_enabled is False
    assert service.subscription_client_name == "Catalog"
    assert service.identity_url == "http://identity-api"
    assert service.identity_url_external == "http://localhost:5105"
    assert service.path_base == "/catalog-api"
    assert service.http_port == 80
    assert service.grpc_port == 81


def test_missing_required_fails_fast_with_actionable_message():
    service = ServiceSettings(make_settings())
    with pytest.raises(ConfigurationError) as exc_info:
        _ = service.connection_string
    assert "ConnectionString" in str(exc_info.value)


def test_missing_required_never_echoes_secret_values():
    settings = make_settings(EventBusPassword="super-secret")
    with pytest.raises(ConfigurationError) as exc_info:
        settings.require_all({"ConnectionString": None, "EventBusConnection": None})
    message = str(exc_info.value)
    assert "super-secret" not in message
    assert "ConnectionString" in message and "EventBusConnection" in message


def test_describe_redacts_secret_like_names():
    settings = make_settings(
        EventBusPassword="super-secret",
        ConnectionString="Server=x;Password=y",
        AzureStorageAccountKey="abc",
        PORT="80",
    )
    snapshot = settings.describe()
    assert snapshot["EventBusPassword"] == "<redacted>"
    assert snapshot["ConnectionString"] == "<redacted>"
    assert snapshot["AzureStorageAccountKey"] == "<redacted>"
    assert snapshot["PORT"] == "80"


def test_bool_parsing_matches_dotnet_conventions():
    assert make_settings(AzureServiceBusEnabled="True").get_bool("AzureServiceBusEnabled") is True
    assert make_settings(AzureServiceBusEnabled="False").get_bool("AzureServiceBusEnabled") is False
    assert make_settings().get_bool("AzureServiceBusEnabled", default=False) is False


def test_int_parsing_failure_is_redacted_for_secret_names():
    settings = make_settings(EventBusRetryCountToken="not-a-number")
    with pytest.raises(ConfigurationError) as exc_info:
        settings.get_int("EventBusRetryCountToken")
    assert "not-a-number" not in str(exc_info.value)
