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
    sales_sync_interval_minutes: int = 15
    returns_sync_interval_minutes: int = 30
    finance_sync_interval_minutes: int = 60
    stock_stale_after_minutes: int = 45
    sales_stale_after_minutes: int = 45
    returns_stale_after_minutes: int = 90
    finance_stale_after_minutes: int = 180

    @classmethod
    def from_env(cls, *, load_env_file: bool = True) -> "Settings":
        if load_env_file:
            load_dotenv(override=False)
        level = os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO"
        if level not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ConfigError("LOG_LEVEL is invalid")
        intervals = {}
        for name, default in (
            ("STOCK_SYNC_INTERVAL_MINUTES", 15),
            ("SALES_SYNC_INTERVAL_MINUTES", 15),
            ("RETURNS_SYNC_INTERVAL_MINUTES", 30),
            ("FINANCE_SYNC_INTERVAL_MINUTES", 60),
        ):
            try:
                value = int(os.getenv(name, str(default)).strip() or str(default))
            except ValueError as exc:
                raise ConfigError(f"{name} must be an integer") from exc
            if value <= 0:
                raise ConfigError(f"{name} must be positive")
            intervals[name] = value
        stale_thresholds = {}
        for name, default in (
            ("STOCK_STALE_AFTER_MINUTES", 45),
            ("SALES_STALE_AFTER_MINUTES", 45),
            ("RETURNS_STALE_AFTER_MINUTES", 90),
            ("FINANCE_STALE_AFTER_MINUTES", 180),
        ):
            try:
                value = int(os.getenv(name, str(default)).strip() or str(default))
            except ValueError as exc:
                raise ConfigError(f"{name} must be an integer") from exc
            if value <= 0:
                raise ConfigError(f"{name} must be positive")
            stale_thresholds[name] = value
        return cls(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            owner_telegram_ids=_owner_ids(os.getenv("OWNER_TELEGRAM_IDS", "")),
            ozon_client_id=os.getenv("OZON_CLIENT_ID", "").strip(),
            ozon_api_key=os.getenv("OZON_API_KEY", "").strip(),
            database_url=os.getenv("DATABASE_URL", "").strip(),
            log_level=level,
            stock_sync_interval_minutes=intervals["STOCK_SYNC_INTERVAL_MINUTES"],
            sales_sync_interval_minutes=intervals["SALES_SYNC_INTERVAL_MINUTES"],
            returns_sync_interval_minutes=intervals["RETURNS_SYNC_INTERVAL_MINUTES"],
            finance_sync_interval_minutes=intervals["FINANCE_SYNC_INTERVAL_MINUTES"],
            stock_stale_after_minutes=stale_thresholds["STOCK_STALE_AFTER_MINUTES"],
            sales_stale_after_minutes=stale_thresholds["SALES_STALE_AFTER_MINUTES"],
            returns_stale_after_minutes=stale_thresholds["RETURNS_STALE_AFTER_MINUTES"],
            finance_stale_after_minutes=stale_thresholds["FINANCE_STALE_AFTER_MINUTES"],
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
