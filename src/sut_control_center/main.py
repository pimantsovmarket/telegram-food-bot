from datetime import date, timedelta

from .config import Settings
from .db.models import Cabinet
from .db.session import create_database
from .logging_config import configure_logging
from .ozon.client import OzonClient
from .services.cabinet_analytics import calculate_cabinet_analytics
from .services.finance_accrual_sync import FinanceAccrualSource, sync_finance_accruals
from .services.posting_sync import PostingSource, sync_postings
from .services.return_sync import ReturnSource, sync_returns
from .services.stock_scheduler import DataSyncScheduler
from .services.stock_sync import StockCatalogSource
from .services.stock_sync import sync_stocks
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

    data_sync_scheduler = None
    if settings.ozon_configured:
        client = OzonClient(settings.ozon_client_id, settings.ozon_api_key)
        stock_source = StockCatalogSource(client)
        posting_source = PostingSource(client)
        return_source = ReturnSource(client)
        finance_source = FinanceAccrualSource(client)

        async def stock_job():
            return await sync_stocks(database.session_factory, active_cabinet.id, stock_source)

        async def posting_job():
            end = date.today()
            return await sync_postings(database.session_factory, active_cabinet.id, posting_source, end - timedelta(days=29), end)

        async def return_job():
            end = date.today()
            return await sync_returns(database.session_factory, active_cabinet.id, return_source, end - timedelta(days=29), end)

        async def finance_job():
            end = date.today()
            return await sync_finance_accruals(database.session_factory, active_cabinet.id, finance_source, end - timedelta(days=6), end)

        data_sync_scheduler = DataSyncScheduler(
            {"stocks": stock_job, "postings": posting_job, "returns": return_job, "finance": finance_job},
            stock_interval_minutes=settings.stock_sync_interval_minutes,
            sales_interval_minutes=settings.sales_sync_interval_minutes,
            returns_interval_minutes=settings.returns_sync_interval_minutes,
            finance_interval_minutes=settings.finance_sync_interval_minutes,
        )
    build_application(settings, analytics_provider, data_sync_scheduler).run_polling()


if __name__ == "__main__":
    main()
