import asyncio
from datetime import date
from decimal import Decimal
import json
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from sut_control_center.db.models import (
    FinanceAccrual,
    FinanceAccrualComponent,
    FinanceAccrualItem,
    FinanceAccrualType,
    Product,
    SyncRun,
)
from sut_control_center.db.repositories import CabinetRepository
from sut_control_center.db.session import create_database
from sut_control_center.ozon.client import OzonClient
from sut_control_center.ozon.errors import OzonHTTPError
from sut_control_center.services.finance_accrual_sync import FinanceAccrualSource, sync_finance_accruals


DAY = date(2026, 9, 13)


def database_with_product(tmp_path: Path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'finance.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    database = create_database(url)
    with database.session_factory.begin() as session:
        cabinet_id = CabinetRepository(session).add("Primary").id
        session.add(
            Product(
                cabinet_id=cabinet_id,
                product_id=101,
                offer_id="A-1",
                name="Product",
                sku=501,
                is_active=True,
            )
        )
    return database, cabinet_id


def finance_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    if request.url.path == "/v1/finance/accrual/types":
        return httpx.Response(
            200,
            json={
                "accrual_types": [
                    {"id": 32, "name": "Logistic", "description": "Logistics"},
                    {"id": 41, "name": "PayPerClick", "description": "Advertising"},
                ]
            },
        )
    if request.url.path == "/v1/finance/accrual/by-day":
        assert body["date"] == DAY.isoformat()
        if body["last_id"] == "":
            return httpx.Response(
                200,
                json={
                    "accruals": [
                        {
                            "accrual_id": 1001,
                            "date": DAY.isoformat(),
                            "total_amount": {"amount": "305.75", "currency": "RUB"},
                            "unit_number": "POSTING-1",
                            "accrued_category": "POSTING",
                            "posting": {
                                "delivery_schema": "Fbo",
                                "products": [
                                    {
                                        "sku": 501,
                                        "quantity": 2,
                                        "commission": {
                                            "seller_price": {"amount": "400.00", "currency": "RUB"},
                                            "sale_price": {"amount": "420.00", "currency": "RUB"},
                                            "sale_amount": {"amount": "400.00", "currency": "RUB"},
                                            "sale_commission": {"amount": "-40.00", "currency": "RUB"},
                                            "commission": {"amount": "-40.00", "currency": "RUB"},
                                            "commission_ratio": 'value:"0.100000"',
                                            "coinvestment": {"amount": "5.00", "currency": "RUB"},
                                            "bonus": {"amount": "0.00", "currency": "RUB"},
                                        },
                                        "delivery": {
                                            "services": [
                                                {"type_id": 32, "accrued": {"amount": "-50.00", "currency": "RUB"}},
                                                {"type_id": 999, "accrued": {"amount": "-4.25", "currency": "RUB"}},
                                            ]
                                        },
                                    },
                                    {"quantity": 1, "commission": {}, "delivery": {"services": []}},
                                ],
                            },
                        }
                    ],
                    "last_id": "next",
                },
            )
        if body["last_id"] == "next":
            return httpx.Response(
                200,
                json={
                    "accruals": [
                        {
                            "accrual_id": 1002,
                            "date": DAY.isoformat(),
                            "total_amount": {"amount": "-7.50", "currency": "RUB"},
                            "accrued_category": "NON_ITEM",
                            "non_item_fee": {
                                "type_id": 41,
                                "accrued": {"amount": "-7.50", "currency": "RUB"},
                            },
                        }
                    ],
                    "last_id": "",
                },
            )
    raise AssertionError(f"Unexpected request: {request.url.path} {body}")


def source(handler=finance_handler) -> FinanceAccrualSource:
    client = OzonClient("client", "key", max_retries=0, transport=httpx.MockTransport(handler))
    return FinanceAccrualSource(client)


def test_finance_sync_preserves_decimal_links_unknown_types_and_non_item(tmp_path, monkeypatch):
    database, cabinet_id = database_with_product(tmp_path, monkeypatch)
    try:
        result = asyncio.run(sync_finance_accruals(database.session_factory, cabinet_id, source(), DAY, DAY))
        with database.session_factory() as session:
            accruals = list(session.scalars(select(FinanceAccrual).order_by(FinanceAccrual.accrual_id)))
            items = list(session.scalars(select(FinanceAccrualItem).order_by(FinanceAccrualItem.id)))
            components = list(session.scalars(select(FinanceAccrualComponent).order_by(FinanceAccrualComponent.id)))
            run = session.get(SyncRun, result.sync_run_id)
            linked = session.scalar(
                select(func.count()).select_from(FinanceAccrualItem).join(Product, Product.sku == FinanceAccrualItem.sku)
            )
            assert [(row.accrual_id, row.category, row.posting_number) for row in accruals] == [
                (1001, "POSTING", "POSTING-1"),
                (1002, "NON_ITEM", None),
            ]
            assert accruals[0].total_amount == Decimal("305.750000")
            assert [(item.sku, item.quantity) for item in items] == [(501, 2), (None, 1)]
            assert items[0].commission_ratio == Decimal("0.100000")
            assert {(item.sku, item.type_id) for item in components} == {(501, 32), (501, 999), (None, 41)}
            assert linked == 1
            assert result.unknown_type_ids == (999,)
            assert run.status == "success" and run.rows_received == 2
    finally:
        database.dispose()


def test_repeated_finance_sync_is_idempotent(tmp_path, monkeypatch):
    database, cabinet_id = database_with_product(tmp_path, monkeypatch)
    try:
        first = asyncio.run(sync_finance_accruals(database.session_factory, cabinet_id, source(), DAY, DAY))
        second = asyncio.run(sync_finance_accruals(database.session_factory, cabinet_id, source(), DAY, DAY))
        with database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(FinanceAccrual)) == 2
            assert session.scalar(select(func.count()).select_from(FinanceAccrualItem)) == 2
            assert session.scalar(select(func.count()).select_from(FinanceAccrualComponent)) == 3
            assert session.scalar(select(func.count()).select_from(FinanceAccrualType)) == 2
            assert session.scalar(select(func.count()).select_from(SyncRun)) == 2
            assert first.accruals_saved == second.accruals_saved == 2
    finally:
        database.dispose()


def test_finance_api_error_records_failed_sync_run(tmp_path, monkeypatch):
    database, cabinet_id = database_with_product(tmp_path, monkeypatch)
    try:
        failing = source(lambda _request: httpx.Response(500))
        with pytest.raises(OzonHTTPError):
            asyncio.run(sync_finance_accruals(database.session_factory, cabinet_id, failing, DAY, DAY))
        with database.session_factory() as session:
            run = session.scalar(select(SyncRun))
            assert run.status == "failed" and run.rows_received == 0 and run.finished_at is not None
            assert not list(session.scalars(select(FinanceAccrual)))
    finally:
        database.dispose()
