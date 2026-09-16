from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError

from sut_control_center.db.models import Product, ProductReplenishmentParameters
from sut_control_center.db.repositories import CabinetRepository, ProductReplenishmentParametersRepository
from sut_control_center.db.session import create_database


def database_with_product(tmp_path: Path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'replenishment.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    database = create_database(url)
    with database.session_factory.begin() as session:
        cabinet_id = CabinetRepository(session).add("Primary").id
        session.add(Product(cabinet_id=cabinet_id, product_id=101, offer_id="A", name="Product", is_active=True))
    return database, cabinet_id


def test_parameter_versions_preserve_history(tmp_path, monkeypatch):
    database, cabinet_id = database_with_product(tmp_path, monkeypatch)
    first_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    second_at = datetime(2026, 9, 15, tzinfo=timezone.utc)
    try:
        with database.session_factory.begin() as session:
            repository = ProductReplenishmentParametersRepository(session)
            first = repository.set_parameters(cabinet_id, 101, 14, 7, first_at)
            first_id = first.id
        with database.session_factory.begin() as session:
            repository = ProductReplenishmentParametersRepository(session)
            second = repository.set_parameters(cabinet_id, 101, 10, 5, second_at)
            second_id = second.id
        with database.session_factory() as session:
            repository = ProductReplenishmentParametersRepository(session)
            old = repository.get_effective(cabinet_id, 101, datetime(2026, 9, 10, tzinfo=timezone.utc))
            current = repository.get_effective(cabinet_id, 101, second_at)
            first = session.get(ProductReplenishmentParameters, first_id)
            versions = session.query(ProductReplenishmentParameters).all()
            assert (old.id, old.lead_time_days, old.safety_stock_days) == (first_id, 14, 7)
            assert (current.id, current.lead_time_days, current.safety_stock_days) == (second_id, 10, 5)
            assert first.effective_to.replace(tzinfo=timezone.utc) == second_at
            assert len(versions) == 2
    finally:
        database.dispose()


def test_multiple_active_versions_are_prevented_by_database(tmp_path, monkeypatch):
    database, cabinet_id = database_with_product(tmp_path, monkeypatch)
    try:
        with pytest.raises(IntegrityError):
            with database.session_factory.begin() as session:
                session.add_all(
                    [
                        ProductReplenishmentParameters(
                            cabinet_id=cabinet_id,
                            product_id=101,
                            lead_time_days=14,
                            safety_stock_days=7,
                            effective_from=datetime(2026, 9, 1, tzinfo=timezone.utc),
                        ),
                        ProductReplenishmentParameters(
                            cabinet_id=cabinet_id,
                            product_id=101,
                            lead_time_days=10,
                            safety_stock_days=5,
                            effective_from=datetime(2026, 9, 2, tzinfo=timezone.utc),
                        ),
                    ]
                )
    finally:
        database.dispose()


@pytest.mark.parametrize("lead_time,safety_stock", [(-1, 0), (0, -1)])
def test_negative_parameters_are_rejected(tmp_path, monkeypatch, lead_time, safety_stock):
    database, cabinet_id = database_with_product(tmp_path, monkeypatch)
    try:
        with database.session_factory() as session:
            repository = ProductReplenishmentParametersRepository(session)
            with pytest.raises(ValueError):
                repository.set_parameters(cabinet_id, 101, lead_time, safety_stock, datetime.now(timezone.utc))
    finally:
        database.dispose()
