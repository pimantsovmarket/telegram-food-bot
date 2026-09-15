from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from ..db.models import SyncRun
from ..db.repositories import PostingRepository, ProductRepository, SyncRunRepository
from ..ozon.client import OzonClient
from ..ozon.errors import OzonResponseError
from ..ozon.models import OzonPosting, OzonPostingItem


@dataclass(frozen=True, slots=True)
class PostingSyncResult:
    sync_run_id: int
    rows_received: int
    items_received: int
    unmatched_items: int


class PostingSource:
    def __init__(self, client: OzonClient, *, page_size: int = 100) -> None:
        self.client = client
        self.page_size = page_size

    async def fetch(self, period_start: date, period_end: date) -> list[OzonPosting]:
        since = datetime.combine(period_start, time.min, timezone.utc).isoformat().replace("+00:00", "Z")
        until = datetime.combine(period_end, time.max, timezone.utc).isoformat().replace("+00:00", "Z")
        postings = []
        postings.extend(await self._fetch_pages("/v3/posting/fbo/list", "FBO", since, until))
        postings.extend(await self._fetch_pages("/v4/posting/fbs/list", "FBS", since, until))
        return postings

    async def _fetch_pages(self, path: str, scheme: str, since: str, until: str) -> list[OzonPosting]:
        cursor = ""
        result = []
        while True:
            response = await self.client.post(
                path,
                json={
                    "cursor": cursor,
                    "filter": {"since": since, "to": until},
                    "limit": self.page_size,
                    "sort_dir": "asc",
                    "with": {"analytics_data": False, "financial_data": False, "legal_info": False},
                },
            )
            payload = response.data.get("result", response.data)
            if not isinstance(payload, dict) or not isinstance(payload.get("postings"), list):
                raise OzonResponseError(f"Ozon posting response has an unexpected structure for {path}")
            page = payload["postings"]
            result.extend(self._normalize(posting, scheme) for posting in page)
            has_next = bool(payload.get("has_next", response.data.get("has_next")))
            next_cursor = str(payload.get("cursor", response.data.get("cursor")) or "")
            if not has_next:
                break
            if not next_cursor or next_cursor == cursor:
                raise OzonResponseError(f"Ozon posting pagination cursor is invalid for {path}")
            cursor = next_cursor
        return result

    @staticmethod
    def _normalize(posting: Any, scheme: str) -> OzonPosting:
        if not isinstance(posting, dict):
            raise OzonResponseError("Ozon posting item has an unexpected structure")
        posting_number = posting.get("posting_number")
        status = posting.get("status") or posting.get("status_alias")
        event_at = posting.get("created_at") if scheme == "FBO" else posting.get("in_process_at")
        event_at = event_at or posting.get("in_process_at") or posting.get("created_at")
        products = posting.get("products")
        if not posting_number or not status or not event_at or not isinstance(products, list):
            raise OzonResponseError("Ozon posting identifiers, status, date or products have an unexpected structure")
        try:
            datetime.fromisoformat(str(event_at).replace("Z", "+00:00"))
        except ValueError as exc:
            raise OzonResponseError("Ozon posting event date is invalid") from exc
        items = []
        for product in products:
            if not isinstance(product, dict):
                raise OzonResponseError("Ozon posting product has an unexpected structure")
            offer_id = product.get("offer_id") or product.get("product_offer_id")
            sku = product.get("sku") or product.get("product_id")
            quantity = product.get("quantity")
            if not offer_id or sku is None or quantity is None:
                raise OzonResponseError("Ozon posting product identifiers have an unexpected structure")
            items.append(OzonPostingItem(str(offer_id), int(sku), int(quantity)))
        return OzonPosting(str(posting_number), scheme, str(status), str(event_at), tuple(items))


async def sync_postings(
    session_factory: sessionmaker[Session],
    cabinet_id: int,
    source: PostingSource,
    period_start: date,
    period_end: date,
) -> PostingSyncResult:
    if period_end < period_start:
        raise ValueError("Posting sync period is invalid")
    with session_factory.begin() as session:
        run = SyncRunRepository(session).start(cabinet_id, "ozon_postings", "postings")
        run_id = run.id
        products = ProductRepository(session).list_for_cabinet(cabinet_id)
        product_by_offer = {product.offer_id: product.product_id for product in products}

    try:
        postings = await source.fetch(period_start, period_end)
        items_received = sum(len(posting.items) for posting in postings)
        with session_factory.begin() as session:
            rows_received, _, unmatched_items = PostingRepository(session).upsert_many(
                cabinet_id,
                postings,
                product_by_offer,
            )
            run = session.get(SyncRun, run_id)
            if run is None:
                raise RuntimeError("Posting sync run was not found")
            SyncRunRepository(session).finish(run, status="success", rows_received=rows_received)
        return PostingSyncResult(run_id, rows_received, items_received, unmatched_items)
    except Exception as exc:
        with session_factory.begin() as session:
            run = session.get(SyncRun, run_id)
            if run is not None:
                SyncRunRepository(session).finish(run, status="failed", error_message=str(exc)[:2000])
        raise
