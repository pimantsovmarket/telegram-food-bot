import logging
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

from telegram import Update
from telegram.ext import ContextTypes

from ..config import Settings
from ..services.cabinet_analytics import CabinetAnalytics
from .security import is_owner


UNAUTHORIZED = "Access denied."
STATUS_ERROR = "Не удалось сформировать отчёт. Попробуйте позже."
logger = logging.getLogger(__name__)
AnalyticsProvider = Callable[[date, date], CabinetAnalytics]


def _format_money(value: Decimal) -> str:
    formatted = f"{value:,.2f}"
    return f"{formatted.replace(',', ' ').replace('.', ',')} ₽"


def format_status(report: CabinetAnalytics) -> str:
    period = f"{report.period_start:%d.%m}–{report.period_end:%d.%m}"
    return "\n".join(
        (
            "СУТЬ | Кабинет",
            f"Период: {period}",
            "",
            "Продажи",
            f"• Доставлено: {report.delivered_units} шт.",
            f"• Отменено: {report.cancelled_units} шт.",
            f"• Возвраты клиентов: {report.client_return_units} шт.",
            f"• Полные возвраты: {report.full_return_units} шт.",
            "",
            "Остатки",
            f"• Сейчас: {report.current_stock} шт.",
            "",
            "Ozon",
            f"• Продажи: {_format_money(report.sales_amount)}",
            f"• Комиссии: {_format_money(report.commissions)}",
            f"• Логистика: {_format_money(report.logistics)}",
            f"• Обратная логистика: {_format_money(report.return_logistics)}",
            f"• Хранение: {_format_money(report.storage)}",
            f"• Прочие услуги: {_format_money(report.other_services)}",
            f"• Начислено Ozon: {_format_money(report.finance_accrual_total)}",
        )
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("СУТЬ Control Center запущен. Используйте /status для отчёта.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text("/start — запуск\n/status — отчёт за 30 дней\n/help — команды")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    settings: Settings = context.application.bot_data["settings"]
    user_id = update.effective_user.id if update.effective_user else None
    if not is_owner(user_id, settings.owner_telegram_ids):
        await update.message.reply_text(UNAUTHORIZED)
        return
    provider: AnalyticsProvider | None = context.application.bot_data.get("analytics_provider")
    if provider is None:
        await update.message.reply_text(STATUS_ERROR)
        return
    period_end = date.today()
    period_start = period_end - timedelta(days=29)
    try:
        report = provider(period_start, period_end)
    except Exception:
        logger.exception("Cabinet analytics status failed")
        await update.message.reply_text(STATUS_ERROR)
        return
    await update.message.reply_text(format_status(report))
