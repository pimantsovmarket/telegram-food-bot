from datetime import datetime, timedelta, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config

from sut_control_center.db.models import SyncRun
from sut_control_center.db.repositories import CabinetRepository
from sut_control_center.db.session import create_database
from sut_control_center.services.data_freshness import (
    FreshnessState,
    calculate_data_freshness,
    format_age,
    format_freshness_warning,
)


NOW = datetime(2026, 9, 17, 20, 0, tzinfo=timezone.utc)
THRESHOLDS = {"stocks": 45, "sales": 45, "returns": 90, "finance": 180}
ENTITIES = {"stocks": "stocks", "sales": "postings", "returns": "returns", "finance": "finance_accruals"}


def database_with_cabinets(tmp_path: Path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'freshness.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    database = create_database(url)
    with database.session_factory.begin() as session:
        first = CabinetRepository(session).add("First").id
        second = CabinetRepository(session).add("Second").id
    return database, first, second


def add_run(session, cabinet_id, entity, status, started_at, finished_at=None):
    session.add(
        SyncRun(
            cabinet_id=cabinet_id,
            source="test",
            entity=entity,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
        )
    )


def test_fresh_stale_and_never_synced_states(tmp_path, monkeypatch):
    database, cabinet_id, _ = database_with_cabinets(tmp_path, monkeypatch)
    try:
        with database.session_factory.begin() as session:
            add_run(session, cabinet_id, "stocks", "success", NOW - timedelta(minutes=11), NOW - timedelta(minutes=10))
            add_run(session, cabinet_id, "postings", "success", NOW - timedelta(minutes=47), NOW - timedelta(minutes=46))
            add_run(session, cabinet_id, "returns", "success", NOW - timedelta(minutes=90), NOW - timedelta(minutes=90))
        with database.session_factory() as session:
            report = calculate_data_freshness(session, cabinet_id, THRESHOLDS, now=NOW)
        assert report.get("stocks").state is FreshnessState.FRESH
        assert report.get("sales").state is FreshnessState.STALE
        assert report.get("returns").state is FreshnessState.FRESH
        assert report.get("finance").state is FreshnessState.NEVER_SYNCED
        warning = format_freshness_warning(report)
        assert "Продажи: не обновлялись 46 мин" in warning
        assert "Финансы: ещё не обновлялись" in warning
    finally:
        database.dispose()


def test_failed_run_after_success_preserves_success_and_warns(tmp_path, monkeypatch):
    database, cabinet_id, _ = database_with_cabinets(tmp_path, monkeypatch)
    try:
        with database.session_factory.begin() as session:
            for entity in ENTITIES.values():
                add_run(session, cabinet_id, entity, "success", NOW - timedelta(minutes=11), NOW - timedelta(minutes=10))
            add_run(session, cabinet_id, "stocks", "failed", NOW - timedelta(minutes=2), NOW - timedelta(minutes=1))
        with database.session_factory() as session:
            report = calculate_data_freshness(session, cabinet_id, THRESHOLDS, now=NOW)
        stock = report.get("stocks")
        assert stock.state is FreshnessState.FRESH
        assert stock.failed_after_success
        assert stock.last_success_at == NOW - timedelta(minutes=10)
        assert "последняя синхронизация завершилась ошибкой" in format_freshness_warning(report)
    finally:
        database.dispose()


def test_cabinets_are_not_mixed(tmp_path, monkeypatch):
    database, first, second = database_with_cabinets(tmp_path, monkeypatch)
    try:
        with database.session_factory.begin() as session:
            for entity in ENTITIES.values():
                add_run(session, first, entity, "success", NOW - timedelta(minutes=11), NOW - timedelta(minutes=10))
                add_run(session, second, entity, "success", NOW - timedelta(hours=5), NOW - timedelta(hours=5))
        with database.session_factory() as session:
            first_report = calculate_data_freshness(session, first, THRESHOLDS, now=NOW)
            second_report = calculate_data_freshness(session, second, THRESHOLDS, now=NOW)
        assert not first_report.requires_attention
        assert second_report.requires_attention
    finally:
        database.dispose()


def test_time_formatting():
    assert format_age(timedelta(seconds=30)) == "менее минуты"
    assert format_age(timedelta(hours=1, minutes=12)) == "1 ч 12 мин"
    assert format_age(timedelta(days=2, hours=3, minutes=9)) == "2 д 3 ч"
