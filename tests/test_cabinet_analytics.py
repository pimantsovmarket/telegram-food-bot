from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from sut_control_center.db.models import (
    FinanceAccrual,
    FinanceAccrualComponent,
    FinanceAccrualItem,
    FinanceAccrualType,
    Posting,
    PostingItem,
    Product,
    Return,
    Stock,
)
from sut_control_center.db.repositories import CabinetRepository
from sut_control_center.db.session import create_database
from sut_control_center.services.cabinet_analytics import calculate_cabinet_analytics


START = date(2026, 9, 1)
END = date(2026, 9, 30)


def populated_database(tmp_path: Path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'analytics.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    database = create_database(url)
    at = datetime(2026, 9, 10, tzinfo=timezone.utc)
    with database.session_factory.begin() as session:
        cabinet_id = CabinetRepository(session).add("Primary").id
        session.add_all([
            Product(cabinet_id=cabinet_id, product_id=101, offer_id="A", name="A", sku=501, size="M"),
            Product(cabinet_id=cabinet_id, product_id=102, offer_id="B", name="B", sku=502, size="L"),
        ])
        session.flush()
        delivered = Posting(cabinet_id=cabinet_id, posting_number="D", scheme="FBO", status="delivered", event_at=at)
        delivered_fbs = Posting(cabinet_id=cabinet_id, posting_number="D-FBS", scheme="FBS", status="delivered", event_at=at)
        cancelled = Posting(cabinet_id=cabinet_id, posting_number="C", scheme="FBO", status="cancelled", event_at=at)
        session.add_all([delivered, delivered_fbs, cancelled])
        session.flush()
        session.add_all([
            PostingItem(posting_id=delivered.id, cabinet_id=cabinet_id, product_id=101, offer_id="A", sku=501, quantity=3, match_status="matched"),
            PostingItem(posting_id=delivered_fbs.id, cabinet_id=cabinet_id, product_id=102, offer_id="B", sku=502, quantity=2, match_status="matched"),
            PostingItem(posting_id=cancelled.id, cabinet_id=cabinet_id, product_id=102, offer_id="B", sku=502, quantity=2, match_status="matched"),
            Stock(cabinet_id=cabinet_id, product_id=101, offer_id="A", stock_type="fbo", sku=501, present=10, reserved=2),
            Stock(cabinet_id=cabinet_id, product_id=102, offer_id="B", stock_type="fbo", sku=502, present=1, reserved=3),
            Return(return_id=1, cabinet_id=cabinet_id, schema="Fbo", type="ClientReturn", product_id=101, sku=501, quantity=1, return_date=at),
            Return(return_id=2, cabinet_id=cabinet_id, schema="Fbo", type="FullReturn", quantity=2, return_date=at),
            Return(return_id=3, cabinet_id=cabinet_id, schema="Fbo", type="Cancellation", product_id=101, quantity=9, return_date=at),
        ])
        session.add_all([
            FinanceAccrualType(type_id=32, name="Logistic", description=""),
            FinanceAccrualType(type_id=59, name="ReturnFlowLogistic", description=""),
            FinanceAccrualType(type_id=46, name="Placements", description=""),
            FinanceAccrualType(type_id=1, name="Acquiring", description=""),
        ])
        accrual = FinanceAccrual(accrual_id=100, cabinet_id=cabinet_id, operation_date=at.date(), category="POSTING", total_amount=Decimal("500"), currency="RUB")
        session.add(accrual)
        session.flush()
        session.add(FinanceAccrualItem(accrual_id=100, sku=501, quantity=1, sale_amount=Decimal("700"), commission=Decimal("-100")))
        session.add_all([
            FinanceAccrualComponent(accrual_id=100, type_id=32, amount=Decimal("-20"), currency="RUB"),
            FinanceAccrualComponent(accrual_id=100, type_id=59, amount=Decimal("-10"), currency="RUB"),
            FinanceAccrualComponent(accrual_id=100, type_id=46, amount=Decimal("-5"), currency="RUB"),
            FinanceAccrualComponent(accrual_id=100, type_id=1, amount=Decimal("-3"), currency="RUB"),
        ])
    return database, cabinet_id


def test_cabinet_analytics_uses_distinct_sources_and_no_double_counting(tmp_path, monkeypatch):
    database, cabinet_id = populated_database(tmp_path, monkeypatch)
    try:
        with database.session_factory() as session:
            result = calculate_cabinet_analytics(session, cabinet_id, START, END)
        assert result.delivered_units == 5
        assert result.delivered_units_fbo == 3
        assert result.delivered_units_fbs == 2
        assert result.delivered_units_total == 5
        assert result.delivered_units_fbo + result.delivered_units_fbs == result.delivered_units_total
        assert result.cancelled_units == 2
        assert result.client_return_units == 1
        assert result.full_return_units == 2
        assert result.unlinked_returns == 2
        assert result.current_stock == 8
        assert result.finance_accrual_total == Decimal("500")
        assert result.sales_amount == Decimal("700")
        assert result.commissions == Decimal("-100")
        assert result.logistics == Decimal("-20")
        assert result.return_logistics == Decimal("-10")
        assert result.storage == Decimal("-5")
        assert result.other_services == Decimal("-3")
        assert [(row.product_id, row.size, row.delivered_units_fbo, row.delivered_units_fbs, row.delivered_units_total, row.cancelled_units, row.return_units, row.current_stock) for row in result.product_breakdown] == [
            (101, "M", 3, 0, 3, 0, 1, 8),
            (102, "L", 0, 2, 2, 2, 0, 0),
        ]
    finally:
        database.dispose()


def test_cabinet_analytics_respects_period_and_zero_values(tmp_path, monkeypatch):
    database, cabinet_id = populated_database(tmp_path, monkeypatch)
    try:
        with database.session_factory() as session:
            result = calculate_cabinet_analytics(session, cabinet_id, date(2026, 8, 1), date(2026, 8, 31))
        assert result.delivered_units == result.cancelled_units == 0
        assert result.client_return_units == result.full_return_units == 0
        assert result.finance_accrual_total == result.sales_amount == result.commissions == Decimal("0")
        assert result.current_stock == 8
    finally:
        database.dispose()


def test_cabinet_analytics_rejects_invalid_period(tmp_path, monkeypatch):
    database, cabinet_id = populated_database(tmp_path, monkeypatch)
    try:
        with database.session_factory() as session, pytest.raises(ValueError):
            calculate_cabinet_analytics(session, cabinet_id, END, START)
    finally:
        database.dispose()


def test_cabinet_analytics_does_not_mix_cabinets(tmp_path, monkeypatch):
    database, cabinet_id = populated_database(tmp_path, monkeypatch)
    try:
        at = datetime(2026, 9, 10, tzinfo=timezone.utc)
        with database.session_factory.begin() as session:
            other_id = CabinetRepository(session).add("Other").id
            session.add(Product(cabinet_id=other_id, product_id=201, offer_id="X", name="X", sku=601))
            session.flush()
            posting = Posting(cabinet_id=other_id, posting_number="OTHER", scheme="FBO", status="delivered", event_at=at)
            session.add(posting)
            session.flush()
            session.add(PostingItem(posting_id=posting.id, cabinet_id=other_id, product_id=201, offer_id="X", sku=601, quantity=99, match_status="matched"))
        with database.session_factory() as session:
            result = calculate_cabinet_analytics(session, cabinet_id, START, END)
        assert result.delivered_units_total == 5
        assert all(row.product_id != 201 for row in result.product_breakdown)
    finally:
        database.dispose()
