from datetime import datetime, timedelta, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config

from sut_control_center.db.models import Product, Stock, SyncRun
from sut_control_center.db.repositories import CabinetRepository
from sut_control_center.db.session import create_database
from sut_control_center.services.alerts import AlertsService


NOW = datetime(2026, 9, 17, 20, 0, tzinfo=timezone.utc)
THRESHOLDS = {"stocks": 45, "sales": 45, "returns": 90, "finance": 180}
ENTITIES = ("stocks", "postings", "returns", "finance_accruals")


def database_with_cabinets(tmp_path: Path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'alerts.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    database = create_database(url)
    with database.session_factory.begin() as session:
        first = CabinetRepository(session).add("First").id
        second = CabinetRepository(session).add("Second").id
        session.add_all([
            Product(cabinet_id=first, product_id=101, offer_id="A", name="Out", sku=501, is_active=True),
            Product(cabinet_id=first, product_id=102, offer_id="B", name="Available", sku=502, is_active=True),
            Product(cabinet_id=second, product_id=201, offer_id="C", name="Other", sku=601, is_active=True),
            Stock(cabinet_id=first, product_id=102, offer_id="B", stock_type="fbo", sku=502, present=5, reserved=1),
            Stock(cabinet_id=second, product_id=201, offer_id="C", stock_type="fbo", sku=601, present=3, reserved=0),
        ])
        for cabinet_id in (first, second):
            for entity in ENTITIES:
                session.add(
                    SyncRun(
                        cabinet_id=cabinet_id,
                        source="test",
                        entity=entity,
                        status="success",
                        started_at=NOW - timedelta(minutes=11),
                        finished_at=NOW - timedelta(minutes=10),
                    )
                )
    return database, first, second


def test_zero_stock_creates_alert_and_positive_stock_does_not(tmp_path, monkeypatch):
    database, cabinet_id, _ = database_with_cabinets(tmp_path, monkeypatch)
    try:
        with database.session_factory() as session:
            alerts = AlertsService(session, THRESHOLDS).get_active(cabinet_id, now=NOW)
        stock_alerts = [alert for alert in alerts if alert.type == "STOCK_OUT"]
        assert len(stock_alerts) == 1
        assert "product_id 101" in stock_alerts[0].message
        assert "product_id 102" not in stock_alerts[0].message
    finally:
        database.dispose()


def test_stale_source_creates_data_stale_alert(tmp_path, monkeypatch):
    database, cabinet_id, _ = database_with_cabinets(tmp_path, monkeypatch)
    try:
        with database.session_factory.begin() as session:
            run = session.query(SyncRun).filter_by(cabinet_id=cabinet_id, entity="postings").one()
            run.started_at = NOW - timedelta(hours=2)
            run.finished_at = NOW - timedelta(hours=2)
        with database.session_factory() as session:
            alerts = AlertsService(session, THRESHOLDS).get_active(cabinet_id, now=NOW)
        stale = [alert for alert in alerts if alert.type == "DATA_STALE"]
        assert len(stale) == 1
        assert stale[0].severity == "warning" and "Продажи" in stale[0].message
    finally:
        database.dispose()


def test_alerts_are_scoped_to_cabinet(tmp_path, monkeypatch):
    database, first, second = database_with_cabinets(tmp_path, monkeypatch)
    try:
        with database.session_factory.begin() as session:
            run = session.query(SyncRun).filter_by(cabinet_id=second, entity="stocks").one()
            run.started_at = NOW - timedelta(hours=2)
            run.finished_at = NOW - timedelta(hours=2)
        with database.session_factory() as session:
            first_alerts = AlertsService(session, THRESHOLDS).get_active(first, now=NOW)
            second_alerts = AlertsService(session, THRESHOLDS).get_active(second, now=NOW)
        assert any(alert.type == "STOCK_OUT" for alert in first_alerts)
        assert not any(alert.type == "STOCK_OUT" for alert in second_alerts)
        assert not any(alert.type == "DATA_STALE" for alert in first_alerts)
        assert any(alert.type == "DATA_STALE" for alert in second_alerts)
    finally:
        database.dispose()
