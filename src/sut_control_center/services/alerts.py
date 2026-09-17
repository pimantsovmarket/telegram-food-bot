from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import Product
from .data_freshness import (
    SOURCE_LABELS,
    FreshnessState,
    calculate_data_freshness,
    format_age,
)
from .stock_analytics import calculate_stock_analytics


@dataclass(frozen=True, slots=True)
class Alert:
    type: str
    severity: str
    message: str


class AlertsService:
    def __init__(self, session: Session, stale_after_minutes: dict[str, int]) -> None:
        self.session = session
        self.stale_after_minutes = stale_after_minutes

    def get_active(self, cabinet_id: int, *, now: datetime | None = None) -> list[Alert]:
        active_products = {
            product_id: sku
            for product_id, sku in self.session.execute(
                select(Product.product_id, Product.sku).where(
                    Product.cabinet_id == cabinet_id,
                    Product.is_active.is_(True),
                )
            )
        }
        stock_rows = calculate_stock_analytics(self.session, cabinet_id)
        alerts = []
        for row in stock_rows:
            if row.product_id not in active_products or row.current_stock != 0:
                continue
            sku = active_products[row.product_id]
            identity = f"product_id {row.product_id}"
            if sku is not None:
                identity = f"{identity}, SKU {sku}"
            alerts.append(Alert("STOCK_OUT", "critical", f"Нет остатка: {identity}"))

        freshness = calculate_data_freshness(
            self.session,
            cabinet_id,
            self.stale_after_minutes,
            now=now,
        )
        for item in freshness.sources:
            if item.state is FreshnessState.FRESH and not item.failed_after_success:
                continue
            label = SOURCE_LABELS[item.source]
            if item.state is FreshnessState.NEVER_SYNCED:
                detail = "ещё не синхронизировались"
            else:
                detail = f"не обновлялись {format_age(item.age)}"
            if item.failed_after_success:
                detail = f"последняя синхронизация завершилась ошибкой; {detail}"
            alerts.append(Alert("DATA_STALE", "warning", f"{label}: {detail}"))
        return alerts
