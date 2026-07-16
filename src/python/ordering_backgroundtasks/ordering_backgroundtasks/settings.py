"""Background-task settings honoring the exact compose environment-variable
interface (`ConnectionString`, `EventBusConnection`, `GracePeriodTime`,
`CheckUpdateTime`, `SubscriptionClientName`)."""

from __future__ import annotations

from eshop_common.config import ServiceSettings, Settings

from ordering_backgroundtasks.dbconn import ado_to_sqlalchemy_url


class BackgroundTaskSettings(ServiceSettings):
    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings)

    @property
    def grace_period_time(self) -> int:
        """Minutes an order stays in the grace period (appsettings default 1)."""
        return self.settings.get_int("GracePeriodTime", 1) or 1

    @property
    def check_update_time(self) -> int:
        """Polling delay in milliseconds (appsettings default 1000)."""
        return self.settings.get_int("CheckUpdateTime", 1000) or 1000

    def sqlalchemy_url(self) -> str:
        return ado_to_sqlalchemy_url(self.connection_string)
