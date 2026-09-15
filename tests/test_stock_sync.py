import asyncio
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from sut_control_center.db.models import Product, Stock, SyncRun
from sut_control_center.db.repositories import CabinetRepository
from sut_control_center.db.session import create_database
from sut_control_center.ozon.client import OzonClient
from sut_control_center.ozon.errors import OzonHTTPError
from sut_control_center.services.stock_sync import StockCatalogSource, sync_stocks


def database_with_product(tmp_path: Path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'stocks.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    database = create_database(url)
    with database.session_factory.begin() as session:
        cabinet_id = CabinetRepository(session).add("Primary").id
        session.add(Product(cabinet_id=cabinet_id, product_id=101, offer_id="A-1", name="Product A", is_active=True))
    return database, cabinet_id


def stock_handler(present: int):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v4/product/info/stocks"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "product_id": 101,
                        "offer_id": "A-1",
                        "stocks": [{"type": "fbs", "sku": 501, "present": present, "reserved": 2}],
                    }
                ],
                "cursor": "",
                "total": 1,
            },
        )
    return handler


def source(handler) -> StockCatalogSource:
    client = OzonClient("client", "key", max_retries=0, transport=httpx.MockTransport(handler))
    return StockCatalogSource(client)


def test_successful_stock_sync(tmp_path, monkeypatch):
    database, cabinet_id = database_with_product(tmp_path, monkeypatch)
    try:
        result = asyncio.run(sync_stocks(database.session_factory, cabinet_id, source(stock_handler(8))))
        with database.session_factory() as session:
            stock = session.scalar(select(Stock))
            run = session.get(SyncRun, result.sync_run_id)
            assert (stock.product_id, stock.stock_type, stock.sku, stock.present, stock.reserved) == (101, "fbs", 501, 8, 2)
            assert run.status == "success" and run.rows_received == 1
    finally:
        database.dispose()


def test_repeated_stock_sync_updates_without_duplicates(tmp_path, monkeypatch):
    database, cabinet_id = database_with_product(tmp_path, monkeypatch)
    try:
        asyncio.run(sync_stocks(database.session_factory, cabinet_id, source(stock_handler(8))))
        asyncio.run(sync_stocks(database.session_factory, cabinet_id, source(stock_handler(3))))
        with database.session_factory() as session:
            stocks = list(session.scalars(select(Stock)))
            assert len(stocks) == 1
            assert stocks[0].present == 3
            assert len(list(session.scalars(select(SyncRun)))) == 2
    finally:
        database.dispose()


def test_ozon_error_records_failed_stock_sync(tmp_path, monkeypatch):
    database, cabinet_id = database_with_product(tmp_path, monkeypatch)
    try:
        with pytest.raises(OzonHTTPError):
            asyncio.run(sync_stocks(database.session_factory, cabinet_id, source(lambda _: httpx.Response(500))))
        with database.session_factory() as session:
            run = session.scalar(select(SyncRun))
            assert run.status == "failed" and run.rows_received == 0
            assert "HTTP 500" in run.error_message
            assert not list(session.scalars(select(Stock)))
    finally:
        database.dispose()
