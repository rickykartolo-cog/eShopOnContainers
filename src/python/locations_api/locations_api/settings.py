"""Location settings honoring the exact compose environment-variable interface
(`ConnectionString` [MongoDB URL], `Database`, `identityUrl`, `IdentityUrlExternal`,
`EventBusConnection`, `SubscriptionClientName`, `AzureServiceBusEnabled`,
`UseLoadTest`, `PORT`, `PATH_BASE`)."""

from __future__ import annotations

from eshop_common.config import ServiceSettings, Settings


class LocationSettings(ServiceSettings):
    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings)

    @property
    def database(self) -> str:
        return self.settings.get("Database") or "LocationsDb"

    @property
    def use_load_test(self) -> bool:
        return self.settings.get_bool("UseLoadTest", False)
