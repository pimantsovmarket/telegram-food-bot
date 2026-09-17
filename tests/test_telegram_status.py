import asyncio
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from sut_control_center.config import Settings
from sut_control_center.services.cabinet_analytics import CabinetAnalytics
from sut_control_center.telegram.handlers import STATUS_ERROR, format_status, status


def report(start=date(2026, 8, 19), end=date(2026, 9, 17)) -> CabinetAnalytics:
    return CabinetAnalytics(
        period_start=start,
        period_end=end,
        delivered_units=17,
        cancelled_units=5,
        client_return_units=2,
        full_return_units=1,
        current_stock=7,
        finance_accrual_total=Decimal("609.23"),
        sales_amount=Decimal("2097"),
        commissions=Decimal("-943.65"),
        logistics=Decimal("-364.91"),
        return_logistics=Decimal("-67"),
        storage=Decimal("-68.8"),
        other_services=Decimal("-43.41"),
        product_breakdown=(),
        unlinked_returns=0,
    )


class Message:
    def __init__(self):
        self.replies = []

    async def reply_text(self, value):
        self.replies.append(value)


def context(provider):
    settings = Settings("token", frozenset({42}), "", "", "sqlite:///db")
    return SimpleNamespace(application=SimpleNamespace(bot_data={"settings": settings, "analytics_provider": provider}))


def update(user_id):
    return SimpleNamespace(message=Message(), effective_user=SimpleNamespace(id=user_id))


def test_status_formatting_is_compact_and_labels_accrual_correctly():
    text = format_status(report())
    assert "Период: 19.08–17.09" in text
    assert "Продажи: 2 097,00 ₽" in text
    assert "Комиссии: -943,65 ₽" in text
    assert "Начислено Ozon: 609,23 ₽" in text
    assert "чистая прибыль" not in text.lower()


def test_status_is_owner_only_and_does_not_call_provider():
    called = False

    def provider(_start, _end):
        nonlocal called
        called = True
        return report()

    request = update(7)
    asyncio.run(status(request, context(provider)))
    assert request.message.replies == ["Access denied."]
    assert not called


def test_status_passes_last_30_calendar_days(monkeypatch):
    captured = []

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 17)

    monkeypatch.setattr("sut_control_center.telegram.handlers.date", FixedDate)

    def provider(start, end):
        captured.append((start, end))
        return report(start, end)

    request = update(42)
    asyncio.run(status(request, context(provider)))
    assert captured == [(date(2026, 8, 19), date(2026, 9, 17))]
    assert "Доставлено: 17 шт." in request.message.replies[0]


def test_status_hides_internal_errors():
    def provider(_start, _end):
        raise RuntimeError("secret database detail")

    request = update(42)
    asyncio.run(status(request, context(provider)))
    assert request.message.replies == [STATUS_ERROR]
    assert "secret" not in request.message.replies[0]
