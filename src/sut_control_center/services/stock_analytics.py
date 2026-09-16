from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..db.models import Posting, PostingItem, Product, Stock


@dataclass(frozen=True, slots=True)
class ProductStockAnalytics:
    product_id: int
    current_stock: int
    delivered_units_7d: int
    delivered_units_14d: int
    delivered_units_30d: int
    avg_sales_per_day_7d: float
    avg_sales_per_day_14d: float
    avg_sales_per_day_30d: float
    days_cover_7d: float | None
    days_cover_14d: float | None
    days_cover_30d: float | None


def _days_cover(current_stock: int, average: float) -> float | None:
    return None if average == 0 else current_stock / average


def calculate_stock_analytics(
    session: Session,
    cabinet_id: int,
    *,
    as_of: date | None = None,
) -> list[ProductStockAnalytics]:
    calculation_date = as_of or date.today()
    start_7d = calculation_date - timedelta(days=6)
    start_14d = calculation_date - timedelta(days=13)
    start_30d = calculation_date - timedelta(days=29)
    start_7d_at = datetime.combine(start_7d, time.min, timezone.utc)
    start_14d_at = datetime.combine(start_14d, time.min, timezone.utc)
    start_30d_at = datetime.combine(start_30d, time.min, timezone.utc)
    end_at = datetime.combine(calculation_date + timedelta(days=1), time.min, timezone.utc)

    available_stock = case(
        (Stock.present > Stock.reserved, Stock.present - Stock.reserved),
        else_=0,
    )
    stock_totals = (
        select(
            Stock.cabinet_id.label("cabinet_id"),
            Stock.product_id.label("product_id"),
            func.sum(available_stock).label("current_stock"),
        )
        .where(Stock.cabinet_id == cabinet_id)
        .group_by(Stock.cabinet_id, Stock.product_id)
        .subquery()
    )

    sales_totals = (
        select(
            Posting.cabinet_id.label("cabinet_id"),
            PostingItem.product_id.label("product_id"),
            func.sum(case((Posting.event_at >= start_7d_at, PostingItem.quantity), else_=0)).label("units_7d"),
            func.sum(case((Posting.event_at >= start_14d_at, PostingItem.quantity), else_=0)).label("units_14d"),
            func.sum(PostingItem.quantity).label("units_30d"),
        )
        .join(PostingItem, PostingItem.posting_id == Posting.id)
        .where(
            Posting.cabinet_id == cabinet_id,
            Posting.status == "delivered",
            Posting.event_at >= start_30d_at,
            Posting.event_at < end_at,
            PostingItem.product_id.is_not(None),
        )
        .group_by(Posting.cabinet_id, PostingItem.product_id)
        .subquery()
    )

    statement = (
        select(
            Product.product_id,
            func.coalesce(stock_totals.c.current_stock, 0),
            func.coalesce(sales_totals.c.units_7d, 0),
            func.coalesce(sales_totals.c.units_14d, 0),
            func.coalesce(sales_totals.c.units_30d, 0),
        )
        .outerjoin(
            stock_totals,
            (stock_totals.c.cabinet_id == Product.cabinet_id)
            & (stock_totals.c.product_id == Product.product_id),
        )
        .outerjoin(
            sales_totals,
            (sales_totals.c.cabinet_id == Product.cabinet_id)
            & (sales_totals.c.product_id == Product.product_id),
        )
        .where(Product.cabinet_id == cabinet_id)
        .order_by(Product.product_id)
    )

    analytics = []
    for product_id, current_stock, units_7d, units_14d, units_30d in session.execute(statement):
        current_stock = int(current_stock)
        units_7d = int(units_7d)
        units_14d = int(units_14d)
        units_30d = int(units_30d)
        average_7d = units_7d / 7
        average_14d = units_14d / 14
        average_30d = units_30d / 30
        analytics.append(
            ProductStockAnalytics(
                product_id=int(product_id),
                current_stock=current_stock,
                delivered_units_7d=units_7d,
                delivered_units_14d=units_14d,
                delivered_units_30d=units_30d,
                avg_sales_per_day_7d=average_7d,
                avg_sales_per_day_14d=average_14d,
                avg_sales_per_day_30d=average_30d,
                days_cover_7d=_days_cover(current_stock, average_7d),
                days_cover_14d=_days_cover(current_stock, average_14d),
                days_cover_30d=_days_cover(current_stock, average_30d),
            )
        )
    return analytics
