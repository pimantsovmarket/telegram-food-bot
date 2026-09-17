from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(ValueError):
    """Raised when environment configuration is malformed."""


def _owner_ids(raw: str) -> frozenset[int]:
    if not raw.strip():
        return frozenset()
    try:
        values = frozenset(int(value.strip()) for value in raw.split(",") if value.strip())
    except ValueError as exc:
        raise ConfigError("OWNER_TELEGRAM_IDS must contain comma-separated integers") from exc
    if any(value <= 0 for value in values):
        raise ConfigError("OWNER_TELEGRAM_IDS must contain positive integers")
    return values


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_bot_token: str
    owner_telegram_ids: frozenset[int]
    ozon_client_id: str
    ozon_api_key: str
    database_url: str
    log_level: str = "INFO"
    stock_sync_interval_minutes: int = 15

    @classmethod
    def from_env(cls, *, load_env_file: bool = True) -> "Settings":
        if load_env_file:
            load_dotenv(override=False)
        level = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
        if level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ConfigError("LOG_LEVEL is invalid")
        try:
            stock_sync_interval = int(os.getenv("STOCK_SYNC_INTERVAL_MINUTES", "15").strip() or "15")
        except ValueError as exc:
            raise ConfigError("STOCK_SYNC_INTERVAL_MINUTES must be an integer") from exc
        if stock_sync_interval <= 0:
            raise ConfigError("STOCK_SYNC_INTERVAL_MINUTES must be positive")
        return cls(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            owner_telegram_ids=_owner_ids(os.getenv("OWNER_TELEGRAM_IDS", "")),
            ozon_client_id=os.getenv("OZON_CLIENT_ID", "").strip(),
            ozon_api_key=os.getenv("OZON_API_KEY", "").strip(),
            database_url=os.getenv("DATABASE_URL", "").strip(),
            log_level=level,
            stock_sync_interval_minutes=stock_sync_interval,
        )

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.owner_telegram_ids)

    @property
    def ozon_configured(self) -> bool:
        return bool(self.ozon_client_id and self.ozon_api_key)

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url)

    def secret_values(self) -> tuple[str, ...]:
        return tuple(value for value in (self.telegram_bot_token, self.ozon_api_key, self.ozon_client_id) if value)
