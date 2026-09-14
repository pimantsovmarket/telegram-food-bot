from telegram import Update
from telegram.ext import ContextTypes

from ..config import Settings
from ..health import OzonProbe, check_health
from .security import is_owner


UNAUTHORIZED = "Access denied."


def _dependencies(context: ContextTypes.DEFAULT_TYPE) -> tuple[Settings, OzonProbe | None]:
    return context.application.bot_data["settings"], context.application.bot_data.get("ozon_probe")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("SUT Control Center is running. Use /status for system health.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("/start - start\n/status - system health\n/help - commands")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    settings, probe = _dependencies(context)
    user_id = update.effective_user.id if update.effective_user else None
    if not is_owner(user_id, settings.owner_telegram_ids):
        await update.message.reply_text(UNAUTHORIZED)
        return
    report = await check_health(settings, probe)
    await update.message.reply_text(report.render())
