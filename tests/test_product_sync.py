import asyncio
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from sut_control_center.db.models import Product, SyncRun
from sut_control_center.db.repositories import CabinetRepository
from sut_control_center.db.session import create_database
from sut_control_center.ozon.client import OzonClient
from sut_control_center.ozon.errors import OzonHTTPError
from sut_control_center.services.product_sync import ProductCatalogSource, sync_products


def database_with_cabinet(tmp_path: Path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'products.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    database = create_database(url)
    with database.session_factory.begin() as session:
        cabinet_id = CabinetRepository(session).add("Primary").id
    return database, cabinet_id


def catalog_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v3/product/list":
        return httpx.Response(200, json={"result": {"items": [{"product_id": 101, "offer_id": "A-1"}], "last_id": ""}})
    if request.url.path == "/v3/product/info/list":
        return httpx.Response(200, json={"items": [{"id": 101, "offer_id": "A-1", "name": "Product A", "is_archived": False}]})
    raise AssertionError(f"Unexpected path: {request.url.path}")


def source(handler=catalog_handler) -> ProductCatalogSource:
    client = OzonClient("client", "key", max_retries=0, transport=httpx.MockTransport(handler))
    return ProductCatalogSource(client)


def test_successful_product_sync(tmp_path, monkeypatch):
    database, cabinet_id = database_with_cabinet(tmp_path, monkeypatch)
    try:
        result = asyncio.run(sync_products(database.session_factory, cabinet_id, source()))
        with database.session_factory() as session:
            products = list(session.scalars(select(Product)))
            run = session.get(SyncRun, result.sync_run_id)
            assert [(item.product_id, item.offer_id, item.name) for item in products] == [(101, "A-1", "Product A")]
            assert run.status == "success" and run.rows_received == 1 and run.finished_at is not None
    finally:
        database.dispose()


def test_repeated_sync_updates_without_duplicates(tmp_path, monkeypatch):
    database, cabinet_id = database_with_cabinet(tmp_path, monkeypatch)
    try:
        asyncio.run(sync_products(database.session_factory, cabinet_id, source()))
        asyncio.run(sync_products(database.session_factory, cabinet_id, source()))
        with database.session_factory() as session:
            assert len(list(session.scalars(select(Product)))) == 1
            assert len(list(session.scalars(select(SyncRun)))) == 2
    finally:
        database.dispose()


def test_ozon_error_records_failed_sync_run(tmp_path, monkeypatch):
    database, cabinet_id = database_with_cabinet(tmp_path, monkeypatch)
    failing = source(lambda _request: httpx.Response(500))
    try:
        with pytest.raises(OzonHTTPError):
            asyncio.run(sync_products(database.session_factory, cabinet_id, failing))
        with database.session_factory() as session:
            run = session.scalar(select(SyncRun))
            assert run.status == "failed" and run.rows_received == 0 and run.finished_at is not None
            assert "HTTP 500" in run.error_message
            assert not list(session.scalars(select(Product)))
    finally:
        database.dispose()


def test_unexpected_error_records_failed_sync_run(tmp_path, monkeypatch):
    database, cabinet_id = database_with_cabinet(tmp_path, monkeypatch)

    class UnexpectedFailureSource:
        async def fetch_all(self):
            raise RuntimeError("unexpected failure")

    try:
        with pytest.raises(RuntimeError, match="unexpected failure"):
            asyncio.run(sync_products(database.session_factory, cabinet_id, UnexpectedFailureSource()))
        with database.session_factory() as session:
            run = session.scalar(select(SyncRun))
            assert run.status == "failed" and run.rows_received == 0 and run.finished_at is not None
            assert run.error_message == "unexpected failure"
            assert not list(session.scalars(select(Product)))
    finally:
        database.dispose()
