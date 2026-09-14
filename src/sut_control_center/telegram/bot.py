from telegram.ext import Application, CommandHandler

from ..config import Settings
from ..health import DatabaseProbe, OzonProbe
from .handlers import help_command, start, status


def build_application(settings: Settings, ozon_probe: OzonProbe | None = None, database_probe: DatabaseProbe | None = None) -> Application:
    if not settings.telegram_bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not configured")
    application = Application.builder().token(settings.telegram_bot_token).build()
    application.bot_data["settings"] = settings
    application.bot_data["ozon_probe"] = ozon_probe
    application.bot_data["database_probe"] = database_probe
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status))
    return application
