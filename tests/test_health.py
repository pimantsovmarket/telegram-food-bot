import asyncio

from sut_control_center.config import Settings
from sut_control_center.health import check_health
from sut_control_center.telegram.bot import build_application


def settings() -> Settings:
    return Settings("123456789:TEST_TOKEN", frozenset({42}), "client-id", "api-key", "postgresql://configured")


def test_healthcheck_reports_foundation_status():
    async def reachable():
        return True
    report = asyncio.run(check_health(settings(), reachable))
    assert report.alive and report.config_loaded and report.telegram_configured
    assert report.ozon_configured and report.ozon_reachable and report.database_configured
    assert "ENV:\nSAFE" in report.render()


def test_telegram_bootstrap_registers_minimal_commands():
    application = build_application(settings())
    commands = {command for group in application.handlers.values() for handler in group for command in getattr(handler, "commands", set())}
    assert commands == {"start", "help", "status"}
