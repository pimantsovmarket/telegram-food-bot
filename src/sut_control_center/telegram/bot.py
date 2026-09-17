from telegram.ext import Application, CommandHandler

from ..config import Settings
from ..services.stock_scheduler import DataSyncScheduler
from .handlers import AnalyticsProvider, help_command, start, status


def build_application(
    settings: Settings,
    analytics_provider: AnalyticsProvider | None = None,
    data_sync_scheduler: DataSyncScheduler | None = None,
) -> Application:
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not configured")
    builder = Application.builder().token(settings.telegram_bot_token)
    if data_sync_scheduler is not None:
        builder = builder.post_init(data_sync_scheduler.start).post_shutdown(data_sync_scheduler.stop)
    application = builder.build()
    application.bot_data["settings"] = settings
    application.bot_data["analytics_provider"] = analytics_provider
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status))
    return application
