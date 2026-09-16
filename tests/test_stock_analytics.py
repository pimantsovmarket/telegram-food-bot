from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from sut_control_center.db.models import Posting, PostingItem, Product, Stock
from sut_control_center.db.repositories import CabinetRepository
from sut_control_center.db.session import create_database
from sut_control_center.services.stock_analytics import calculate_stock_analytics


AS_OF = date(2026, 9, 15)


def analytics_database(tmp_path: Path):
    database = create_database(f"sqlite:///{(tmp_path / 'analytics.db').as_posix()}")
    from sut_control_center.db.base import Base

    Base.metadata.create_all(database.engine)
    with database.session_factory.begin() as session:
        cabinet_id = CabinetRepository(session).add("Primary").id
        session.add_all(
            [
                Product(
                    cabinet_id=cabinet_id,
                    product_id=101,
                    offer_id="A",
                    name="Active",
                    sku=1,
                    size="42",
                    color="burgundy",
                    is_active=True,
                ),
                Product(cabinet_id=cabinet_id, product_id=102, offer_id="B", name="No sales", is_active=True),
                Product(cabinet_id=cabinet_id, product_id=103, offer_id="C", name="No stock", is_active=True),
            ]
        )
        session.add_all(
            [
                Stock(cabinet_id=cabinet_id, product_id=101, offer_id="A", stock_type="fbo", sku=1, present=22, reserved=2),
                Stock(cabinet_id=cabinet_id, product_id=102, offer_id="B", stock_type="fbo", sku=2, present=10, reserved=0),
                Stock(cabinet_id=cabinet_id, product_id=103, offer_id="C", stock_type="fbo", sku=3, present=0, reserved=0),
            ]
        )
        sales = [
            ("D-1", "delivered", datetime(2026, 9, 15, tzinfo=timezone.utc), 101, "A", 1, 7),
            ("D-2", "delivered", datetime(2026, 9, 8, tzinfo=timezone.utc), 101, "A", 2, 7),
            ("D-3", "delivered", datetime(2026, 9, 1, tzinfo=timezone.utc), 101, "A", 3, 15),
            ("OLD", "delivered", datetime(2026, 8, 16, tzinfo=timezone.utc), 101, "A", 4, 99),
            ("C-1", "cancelled", datetime(2026, 9, 15, tzinfo=timezone.utc), 101, "A", 5, 50),
            ("D-4", "delivered", datetime(2026, 9, 15, tzinfo=timezone.utc), 103, "C", 6, 7),
        ]
        for posting_number, status, event_at, product_id, offer_id, sku, quantity in sales:
            posting = Posting(
                cabinet_id=cabinet_id,
                posting_number=posting_number,
                scheme="FBO",
                status=status,
                event_at=event_at,
            )
            session.add(posting)
            session.flush()
            session.add(
                PostingItem(
                    posting_id=posting.id,
                    cabinet_id=cabinet_id,
                    product_id=product_id,
                    offer_id=offer_id,
                    sku=sku,
                    quantity=quantity,
                    match_status="matched",
                )
            )
    return database, cabinet_id


def test_calculates_7_14_and_30_day_windows(tmp_path):
    database, cabinet_id = analytics_database(tmp_path)
    try:
        with database.session_factory() as session:
            result = calculate_stock_analytics(session, cabinet_id, as_of=AS_OF)[0]
        assert (result.offer_id, result.sku, result.size, result.color) == ("A", 1, "42", "burgundy")
        assert result.current_stock == 20
        assert (result.delivered_units_7d, result.delivered_units_14d, result.delivered_units_30d) == (7, 14, 29)
        assert result.avg_sales_per_day_7d == pytest.approx(1)
        assert result.avg_sales_per_day_14d == pytest.approx(1)
        assert result.avg_sales_per_day_30d == pytest.approx(29 / 30)
        assert result.days_cover_7d == pytest.approx(20)
        assert result.days_cover_14d == pytest.approx(20)
        assert result.days_cover_30d == pytest.approx(20 / (29 / 30))
    finally:
        database.dispose()


def test_zero_sales_returns_null_days_cover(tmp_path):
    database, cabinet_id = analytics_database(tmp_path)
    try:
        with database.session_factory() as session:
            result = calculate_stock_analytics(session, cabinet_id, as_of=AS_OF)[1]
        assert result.current_stock == 10
        assert result.delivered_units_7d == result.delivered_units_14d == result.delivered_units_30d == 0
        assert result.avg_sales_per_day_7d == result.avg_sales_per_day_14d == result.avg_sales_per_day_30d == 0
        assert result.days_cover_7d is result.days_cover_14d is result.days_cover_30d is None
    finally:
        database.dispose()


def test_zero_stock_returns_zero_days_cover_when_sales_exist(tmp_path):
    database, cabinet_id = analytics_database(tmp_path)
    try:
        with database.session_factory() as session:
            result = calculate_stock_analytics(session, cabinet_id, as_of=AS_OF)[2]
        assert result.current_stock == 0
        assert result.delivered_units_7d == 7
        assert result.days_cover_7d == result.days_cover_14d == result.days_cover_30d == 0
    finally:
        database.dispose()
