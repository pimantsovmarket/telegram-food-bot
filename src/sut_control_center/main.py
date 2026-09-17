from .config import Settings
from .db.models import Cabinet
from .db.session import create_database
from .logging_config import configure_logging
from .ozon.client import OzonClient
from .services.cabinet_analytics import calculate_cabinet_analytics
from .services.stock_scheduler import StockSyncScheduler
from .services.stock_sync import StockCatalogSource
from .telegram.bot import build_application
from sqlalchemy import select


def main() -> None:
    settings = Settings.from_env()
    configure_logging(settings.log_level, settings.secret_values())
    if not settings.telegram_configured:
        raise SystemExit("Telegram configuration is incomplete")
    if not settings.database_configured:
        raise SystemExit("Database configuration is incomplete")
    database = create_database(settings.database_url)
    with database.session_factory() as session:
        active_cabinet = session.scalar(
            select(Cabinet).where(Cabinet.is_active.is_(True)).order_by(Cabinet.id)
        )
    if active_cabinet is None:
        raise SystemExit("No active cabinet configured")

    def analytics_provider(period_start, period_end):
        with database.session_factory() as session:
            cabinet = session.scalar(
                select(Cabinet).where(Cabinet.is_active.is_(True)).order_by(Cabinet.id)
            )
            if cabinet is None:
                raise RuntimeError("No active cabinet configured")
            return calculate_cabinet_analytics(session, cabinet.id, period_start, period_end)

    stock_scheduler = None
    if settings.ozon_configured:
        stock_scheduler = StockSyncScheduler(
            database.session_factory,
            active_cabinet.id,
            StockCatalogSource(OzonClient(settings.ozon_client_id, settings.ozon_api_key)),
            interval_minutes=settings.stock_sync_interval_minutes,
        )
    build_application(settings, analytics_provider, stock_scheduler).run_polling()


if __name__ == "__main__":
    main()
