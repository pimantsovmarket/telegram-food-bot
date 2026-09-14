from dataclasses import dataclass
from typing import Awaitable, Callable

from .config import Settings


OzonProbe = Callable[[], Awaitable[bool]]
DatabaseProbe = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class HealthReport:
    alive: bool
    config_loaded: bool
    telegram_configured: bool
    ozon_configured: bool
    ozon_reachable: bool
    database_configured: bool
    database_reachable: bool

    def render(self) -> str:
        database_status = "CONFIGURED" if self.database_configured and self.database_reachable else "NOT CONFIGURED"
        return "\n".join(("SUT CONTROL CENTER", "", "BOT:", "RUNNING" if self.alive else "ERROR", "", "CONFIG:", "LOADED" if self.config_loaded else "ERROR", "", "OZON API:", "REACHABLE" if self.ozon_reachable else "UNREACHABLE", "", "DATABASE:", database_status, "", "ENV:", "SAFE"))


async def check_health(settings: Settings, ozon_probe: OzonProbe | None = None, database_probe: DatabaseProbe | None = None) -> HealthReport:
    reachable = False
    if settings.ozon_configured and ozon_probe is not None:
        try:
            reachable = await ozon_probe()
        except Exception:
            reachable = False
    database_reachable = False
    if settings.database_configured and database_probe is not None:
        try:
            database_reachable = database_probe()
        except Exception:
            database_reachable = False
    return HealthReport(True, True, settings.telegram_configured, settings.ozon_configured, reachable, settings.database_configured, database_reachable)
