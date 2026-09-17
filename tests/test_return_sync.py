import asyncio
import json
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select

from sut_control_center.db.models import Product, Return, SyncRun
from sut_control_center.db.repositories import CabinetRepository
from sut_control_center.db.session import create_database
from sut_control_center.ozon.client import OzonClient
from sut_control_center.ozon.errors import OzonHTTPError
from sut_control_center.services.return_sync import ReturnSource, sync_returns


def database_with_products(tmp_path: Path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'returns.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    database = create_database(url)
    with database.session_factory.begin() as session:
        cabinet_id = CabinetRepository(session).add("Primary").id
        session.add_all(
            [
                Product(cabinet_id=cabinet_id, product_id=101, offer_id="A-1", name="A", sku=501),
                Product(cabinet_id=cabinet_id, product_id=102, offer_id="B-1", name="B", sku=502),
                Product(cabinet_id=cabinet_id, product_id=103, offer_id="DUP", name="C", sku=503),
                Product(cabinet_id=cabinet_id, product_id=104, offer_id="DUP", name="D", sku=504),
            ]
        )
    return database, cabinet_id


def return_entry(return_id, schema, *, sku=None, offer_id=None, status="InTransit"):
    return {
        "id": return_id,
        "source_id": return_id - 1,
        "schema": schema,
        "type": "ClientReturn",
        "order_id": 9000 + return_id,
        "order_number": f"ORDER-{return_id}",
        "posting_number": f"POSTING-{return_id}",
        "return_reason_name": "Reason",
        "product": {"sku": sku, "offer_id": offer_id, "quantity": 2},
        "visual": {
            "status": {"id": 1, "sys_name": status, "display_name": status},
            "change_moment": "2026-09-17T10:00:00Z",
        },
        "logistic": {
            "return_date": "2026-09-16T10:00:00Z",
            "final_moment": "2026-09-17T10:00:00Z",
        },
    }


def paginated_handler(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    assert request.url.path == "/v1/returns/list"
    assert body["limit"] == 2
    schema = body["filter"]["return_schema"]
    if schema == "FBO" and body["last_id"] == 0:
        return httpx.Response(200, json={"returns": [return_entry(10, "Fbo", sku=501)], "has_next": True})
    if schema == "FBO" and body["last_id"] == 10:
        return httpx.Response(200, json={"returns": [return_entry(11, "Fbo", sku=999, offer_id="B-1")], "has_next": False})
    if schema == "FBS" and body["last_id"] == 0:
        return httpx.Response(200, json={"returns": [return_entry(12, "Fbs", sku=998, offer_id="DUP")], "has_next": False})
    raise AssertionError(body)


def source(handler=paginated_handler) -> ReturnSource:
    client = OzonClient("client", "key", max_retries=0, transport=httpx.MockTransport(handler))
    return ReturnSource(client, page_size=2)


def test_return_sync_paginates_links_sku_then_unique_offer_and_preserves_unknown(tmp_path, monkeypatch):
    database, cabinet_id = database_with_products(tmp_path, monkeypatch)
    try:
        result = asyncio.run(sync_returns(database.session_factory, cabinet_id, source()))
        with database.session_factory() as session:
            rows = list(session.scalars(select(Return).order_by(Return.return_id)))
            run = session.get(SyncRun, result.sync_run_id)
            assert result.fbo_received == 2 and result.fbs_received == 1
            assert result.total_saved == 3 and result.product_id_linked == 2
            assert [(row.return_id, row.product_id) for row in rows] == [(10, 101), (11, 102), (12, None)]
            assert rows[0].quantity == 2 and rows[0].posting_number == "POSTING-10"
            assert rows[0].status_changed_at is not None and rows[0].return_date is not None
            assert run.status == "success" and run.rows_received == 3
    finally:
        database.dispose()


def test_repeated_return_sync_updates_status_without_duplicates(tmp_path, monkeypatch):
    database, cabinet_id = database_with_products(tmp_path, monkeypatch)
    status = {"value": "InTransit"}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        schema = body["filter"]["return_schema"]
        rows = [return_entry(20, "Fbo", sku=501, status=status["value"])] if schema == "FBO" else []
        return httpx.Response(200, json={"returns": rows, "has_next": False})

    try:
        asyncio.run(sync_returns(database.session_factory, cabinet_id, source(handler)))
        status["value"] = "ReturnedToSeller"
        asyncio.run(sync_returns(database.session_factory, cabinet_id, source(handler)))
        with database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Return)) == 1
            row = session.scalar(select(Return))
            assert row.status_code == "ReturnedToSeller"
            assert session.scalar(select(func.count()).select_from(SyncRun)) == 2
    finally:
        database.dispose()


def test_return_api_error_records_failed_sync_run(tmp_path, monkeypatch):
    database, cabinet_id = database_with_products(tmp_path, monkeypatch)
    try:
        failing = source(lambda _request: httpx.Response(500))
        with pytest.raises(OzonHTTPError):
            asyncio.run(sync_returns(database.session_factory, cabinet_id, failing))
        with database.session_factory() as session:
            run = session.scalar(select(SyncRun))
            assert run.status == "failed" and run.finished_at is not None
            assert session.scalar(select(func.count()).select_from(Return)) == 0
    finally:
        database.dispose()
