from .config import Settings
from .db.session import create_database
from .logging_config import configure_logging
from .ozon.client import OzonClient
from .telegram.bot import build_application


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level, settings.secret_values())
    if not settings.telegram_configured:
        raise SystemExit("Telegram configuration is incomplete")
    probe = None
    if settings.ozon_configured:
        client = OzonClient(settings.ozon_client_id, settings.ozon_api_key)
        probe = client.probe
    database_probe = None
    if settings.database_configured:
        database_probe = create_database(settings.database_url).healthcheck
    build_application(settings, probe, database_probe).run_polling()


if __name__ == "__main__":
    main()
