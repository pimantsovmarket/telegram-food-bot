from dataclasses import dataclass
from typing import Awaitable, Callable

from .config import Settings


OzonProbe = Callable[[], Awaitable[bool]]


@dataclass(frozen=True, slots=True)
class HealthReport:
    alive: bool
    config_loaded: bool
    telegram_configured: bool
    ozon_configured: bool
    ozon_reachable: bool
    database_configured: bool

    def render(self) -> str:
        return "\n".join(("SUT CONTROL CENTER", "", "BOT:", "RUNNING" if self.alive else "ERROR", "", "CONFIG:", "LOADED" if self.config_loaded else "ERROR", "", "OZON API:", "REACHABLE" if self.ozon_reachable else "UNREACHABLE", "", "DATABASE:", "CONFIGURED" if self.database_configured else "NOT CONFIGURED", "", "ENV:", "SAFE"))


async def check_health(settings: Settings, ozon_probe: OzonProbe | None = None) -> HealthReport:
    reachable = False
    if settings.ozon_configured and ozon_probe is not None:
        try:
            reachable = await ozon_probe()
        except Exception:
            reachable = False
    return HealthReport(True, True, settings.telegram_configured, settings.ozon_configured, reachable, settings.database_configured)
