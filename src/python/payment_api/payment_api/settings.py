"""Payment settings honoring the exact compose environment-variable interface
(`PaymentSucceeded`, `EventBusConnection`, `EventBusUserName`, `EventBusPassword`,
`EventBusRetryCount`, `AzureServiceBusEnabled`, `SubscriptionClientName`,
`PORT`, `PATH_BASE`)."""

from __future__ import annotations

from eshop_common.config import ServiceSettings, Settings


class PaymentSettings(ServiceSettings):
    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings)

    @property
    def payment_succeeded(self) -> bool:
        # appsettings.json default: "PaymentSucceeded": true
        return self.settings.get_bool("PaymentSucceeded", True)
