import pytest

from sut_control_center.config import ConfigError, Settings


def test_config_loads_from_environment(monkeypatch):
    values = {"TELEGRAM_BOT_TOKEN": "telegram-secret", "OWNER_TELEGRAM_IDS": "10, 20", "OZON_CLIENT_ID": "client-secret", "OZON_API_KEY": "api-secret", "DATABASE_URL": "sqlite:///sut.db", "LOG_LEVEL": "warning", "STOCK_SYNC_INTERVAL_MINUTES": "20", "SALES_SYNC_INTERVAL_MINUTES": "21", "RETURNS_SYNC_INTERVAL_MINUTES": "31", "FINANCE_SYNC_INTERVAL_MINUTES": "61"}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    settings = Settings.from_env(load_env_file=False)
    assert settings.owner_telegram_ids == frozenset({10, 20})
    assert settings.telegram_configured and settings.ozon_configured and settings.database_configured
    assert settings.log_level == "WARNING"
    assert settings.stock_sync_interval_minutes == 20
    assert settings.sales_sync_interval_minutes == 21
    assert settings.returns_sync_interval_minutes == 31
    assert settings.finance_sync_interval_minutes == 61


def test_config_rejects_invalid_owner_ids(monkeypatch):
    monkeypatch.setenv("OWNER_TELEGRAM_IDS", "owner")
    with pytest.raises(ConfigError, match="comma-separated integers"):
        Settings.from_env(load_env_file=False)


@pytest.mark.parametrize("name", ["STOCK", "SALES", "RETURNS", "FINANCE"])
@pytest.mark.parametrize("value", ["0", "minutes"])
def test_config_rejects_invalid_sync_interval(monkeypatch, name, value):
    monkeypatch.setenv("OWNER_TELEGRAM_IDS", "42")
    monkeypatch.setenv(f"{name}_SYNC_INTERVAL_MINUTES", value)
    with pytest.raises(ConfigError, match=f"{name}_SYNC_INTERVAL_MINUTES"):
        Settings.from_env(load_env_file=False)
