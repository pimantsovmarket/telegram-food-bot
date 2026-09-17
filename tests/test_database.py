from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from sut_control_center.db.repositories import AppStateRepository, CabinetRepository, SyncRunRepository
from sut_control_center.db.session import create_database


def migrated_database(tmp_path: Path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'test.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    return create_database(url)


def test_initial_migration_creates_only_foundation_tables(tmp_path, monkeypatch):
    database = migrated_database(tmp_path, monkeypatch)
    try:
        tables = set(inspect(database.engine).get_table_names())
        assert tables == {
            "alembic_version",
            "app_state",
            "cabinets",
            "finance_accrual_components",
            "finance_accrual_items",
            "finance_accrual_types",
            "finance_accruals",
            "posting_items",
            "postings",
            "product_replenishment_parameters",
            "products",
            "returns",
            "stocks",
            "sync_runs",
        }
        product_columns = {column["name"] for column in inspect(database.engine).get_columns("products")}
        assert {"sku", "size", "color"} <= product_columns
    finally:
        database.dispose()


def test_database_healthcheck_executes_query(tmp_path, monkeypatch):
    database = migrated_database(tmp_path, monkeypatch)
    try:
        assert database.healthcheck()
    finally:
        database.dispose()


def test_repositories_persist_foundation_records(tmp_path, monkeypatch):
    database = migrated_database(tmp_path, monkeypatch)
    try:
        with database.session_factory.begin() as session:
            cabinet = CabinetRepository(session).add("Primary")
            run = SyncRunRepository(session).start(cabinet.id, "ozon", "products")
            SyncRunRepository(session).finish(run, status="success", rows_received=3)
            AppStateRepository(session).set("cursor", {"value": "next"})
        with database.session_factory() as session:
            assert CabinetRepository(session).get(cabinet.id).name == "Primary"
            assert AppStateRepository(session).get("cursor") == {"value": "next"}
            assert session.get(type(run), run.id).rows_received == 3
    finally:
        database.dispose()
