import pytest

from sut_control_center.config import ConfigError, Settings


def test_config_loads_from_environment(monkeypatch):
    values = {"TELEGRAM_BOT_TOKEN": "telegram-secret", "OWNER_TELEGRAM_IDS": "10, 20", "OZON_CLIENT_ID": "client-secret", "OZON_API_KEY": "api-secret", "DATABASE_URL": "sqlite:///sut.db", "LOG_LEVEL": "warning"}
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    settings = Settings.from_env(load_env_file=False)
    assert settings.owner_telegram_ids == frozenset({10, 20})
    assert settings.telegram_configured and settings.ozon_configured and settings.database_configured
    assert settings.log_level == "WARNING"


def test_config_rejects_invalid_owner_ids(monkeypatch):
    monkeypatch.setenv("OWNER_TELEGRAM_IDS", "owner")
    with pytest.raises(ConfigError, match="comma-separated integers"):
        Settings.from_env(load_env_file=False)
