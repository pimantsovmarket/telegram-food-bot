import asyncio
import json
from datetime import date
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

from sut_control_center.db.models import Posting, PostingItem, Product, SyncRun
from sut_control_center.db.repositories import CabinetRepository
from sut_control_center.db.session import create_database
from sut_control_center.ozon.client import OzonClient
from sut_control_center.services.posting_sync import PostingSource, sync_postings


START = date(2026, 8, 17)
END = date(2026, 9, 15)


def database_with_product(tmp_path: Path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'postings.db').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config("alembic.ini"), "head")
    database = create_database(url)
    with database.session_factory.begin() as session:
        cabinet_id = CabinetRepository(session).add("Primary").id
        session.add(Product(cabinet_id=cabinet_id, product_id=101, offer_id="A-1", name="Product A", is_active=True))
    return database, cabinet_id


def posting_handler(fbo_quantity: int = 2, fbs_quantity: int = 3, *, unknown: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v3/posting/fbo/list":
            products = [{"offer_id": "A-1", "quantity": fbo_quantity, "sku": 501}]
            if unknown:
                products.append({"offer_id": "UNKNOWN", "quantity": 4, "sku": 999})
            return httpx.Response(200, json={"postings": [{"posting_number": "FBO-1", "status": "delivered", "created_at": "2026-09-01T08:00:00Z", "products": products}], "cursor": "", "has_next": False})
        if request.url.path == "/v4/posting/fbs/list":
            return httpx.Response(200, json={"postings": [{"posting_number": "FBS-1", "status_alias": "awaiting_deliver", "in_process_at": "2026-09-01T09:00:00Z", "products": [{"product_offer_id": "A-1", "quantity": fbs_quantity, "product_id": "502"}]}], "cursor": "", "has_next": False})
        raise AssertionError(f"Unexpected path: {request.url.path}")
    return handler


def source(handler) -> PostingSource:
    client = OzonClient("client", "key", max_retries=0, transport=httpx.MockTransport(handler))
    return PostingSource(client)


def test_fbs_uses_limit_100_and_cursor_pagination():
    fbs_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path == "/v3/posting/fbo/list":
            return httpx.Response(200, json={"postings": [], "cursor": "", "has_next": False})
        if request.url.path == "/v4/posting/fbs/list":
            fbs_requests.append(body)
            cursor = body["cursor"]
            if cursor == "":
                return httpx.Response(200, json={
                    "postings": [{
                        "posting_number": "FBS-1",
                        "status_alias": "awaiting_deliver",
                        "in_process_at": "2026-09-01T09:00:00Z",
                        "products": [{"product_offer_id": "A-1", "quantity": 1, "product_id": "501"}],
                    }],
                    "cursor": "next-page",
                    "has_next": True,
                })
            if cursor == "next-page":
                return httpx.Response(200, json={
                    "postings": [{
                        "posting_number": "FBS-2",
                        "status_alias": "awaiting_deliver",
                        "in_process_at": "2026-09-02T09:00:00Z",
                        "products": [{"product_offer_id": "A-1", "quantity": 2, "product_id": "502"}],
                    }],
                    "cursor": "",
                    "has_next": False,
                })
        raise AssertionError(f"Unexpected request: {request.url.path} {body}")

    postings = asyncio.run(source(handler).fetch(START, END))

    assert [(body["limit"], body["cursor"]) for body in fbs_requests] == [
        (100, ""),
        (100, "next-page"),
    ]
    assert [posting.posting_number for posting in postings] == ["FBS-1", "FBS-2"]


def test_sync_preserves_postings_and_items_without_aggregation(tmp_path, monkeypatch):
    database, cabinet_id = database_with_product(tmp_path, monkeypatch)
    try:
        result = asyncio.run(sync_postings(database.session_factory, cabinet_id, source(posting_handler()), START, END))
        with database.session_factory() as session:
            postings = list(session.scalars(select(Posting).order_by(Posting.scheme)))
            items = list(session.scalars(select(PostingItem).order_by(PostingItem.sku)))
            run = session.get(SyncRun, result.sync_run_id)
            assert [(p.posting_number, p.scheme, p.status) for p in postings] == [("FBO-1", "FBO", "delivered"), ("FBS-1", "FBS", "awaiting_deliver")]
            assert [(p.scheme, p.event_at.hour) for p in postings] == [("FBO", 8), ("FBS", 9)]
            assert [(i.offer_id, i.sku, i.quantity, i.product_id) for i in items] == [("A-1", 501, 2, 101), ("A-1", 502, 3, 101)]
            assert all(item.match_status == "matched" and item.match_error is None for item in items)
            assert result.rows_received == 2 and result.items_received == 2
            assert run.status == "success" and run.rows_received == 2
    finally:
        database.dispose()


def test_repeated_sync_updates_without_duplicates(tmp_path, monkeypatch):
    database, cabinet_id = database_with_product(tmp_path, monkeypatch)
    try:
        asyncio.run(sync_postings(database.session_factory, cabinet_id, source(posting_handler()), START, END))
        asyncio.run(sync_postings(database.session_factory, cabinet_id, source(posting_handler(7, 8)), START, END))
        with database.session_factory() as session:
            postings = list(session.scalars(select(Posting)))
            items = list(session.scalars(select(PostingItem).order_by(PostingItem.sku)))
            assert len(postings) == 2 and len(items) == 2
            assert [item.quantity for item in items] == [7, 8]
    finally:
        database.dispose()


def test_unknown_product_is_registered_without_rolling_back(tmp_path, monkeypatch):
    database, cabinet_id = database_with_product(tmp_path, monkeypatch)
    try:
        result = asyncio.run(sync_postings(database.session_factory, cabinet_id, source(posting_handler(unknown=True)), START, END))
        with database.session_factory() as session:
            unknown = session.scalar(select(PostingItem).where(PostingItem.offer_id == "UNKNOWN"))
            assert result.unmatched_items == 1
            assert unknown.product_id is None and unknown.match_status == "unmatched"
            assert unknown.match_error == "Unknown offer_id: UNKNOWN"
            assert len(list(session.scalars(select(Posting)))) == 2
    finally:
        database.dispose()


def test_unexpected_error_records_failed_sync_run(tmp_path, monkeypatch):
    database, cabinet_id = database_with_product(tmp_path, monkeypatch)

    class UnexpectedFailureSource:
        async def fetch(self, period_start, period_end):
            raise RuntimeError("unexpected failure")

    try:
        with pytest.raises(RuntimeError, match="unexpected failure"):
            asyncio.run(sync_postings(database.session_factory, cabinet_id, UnexpectedFailureSource(), START, END))
        with database.session_factory() as session:
            run = session.scalar(select(SyncRun))
            assert run.status == "failed" and run.finished_at is not None
            assert run.error_message == "unexpected failure"
    finally:
        database.dispose()
