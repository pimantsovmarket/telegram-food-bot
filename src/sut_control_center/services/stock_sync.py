from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from ..db.models import SyncRun
from ..db.repositories import ProductRepository, StockRepository, SyncRunRepository
from ..ozon.client import OzonClient
from ..ozon.errors import OzonResponseError
from ..ozon.models import OzonStock


@dataclass(frozen=True, slots=True)
class StockSyncResult:
    sync_run_id: int
    rows_received: int


class StockCatalogSource:
    def __init__(self, client: OzonClient, *, page_size: int = 1000) -> None:
        self.client = client
        self.page_size = page_size

    async def fetch(self, product_ids: list[int]) -> list[OzonStock]:
        result: dict[tuple[int, str, int], OzonStock] = {}
        for offset in range(0, len(product_ids), self.page_size):
            chunk = product_ids[offset : offset + self.page_size]
            cursor = ""
            while True:
                response = await self.client.post(
                    "/v4/product/info/stocks",
                    json={
                        "cursor": cursor,
                        "filter": {"product_id": [str(value) for value in chunk], "visibility": "ALL"},
                        "limit": self.page_size,
                    },
                )
                items = response.data.get("items")
                if not isinstance(items, list):
                    raise OzonResponseError("Ozon stock response has an unexpected structure")
                for item in items:
                    for stock in self._normalize_item(item):
                        result[(stock.product_id, stock.stock_type, stock.sku)] = stock
                next_cursor = str(response.data.get("cursor") or "")
                if not items or not next_cursor or next_cursor == cursor:
                    break
                cursor = next_cursor
        return list(result.values())

    @staticmethod
    def _normalize_item(item: Any) -> list[OzonStock]:
        if not isinstance(item, dict) or item.get("product_id") is None or not isinstance(item.get("stocks"), list):
            raise OzonResponseError("Ozon stock item has an unexpected structure")
        normalized = []
        for stock in item["stocks"]:
            required = {"type", "sku", "present", "reserved"}
            if not isinstance(stock, dict) or not required.issubset(stock):
                raise OzonResponseError("Ozon stock entry has an unexpected structure")
            normalized.append(
                OzonStock(
                    product_id=int(item["product_id"]),
                    offer_id=str(item.get("offer_id") or ""),
                    stock_type=str(stock["type"]),
                    sku=int(stock["sku"]),
                    present=int(stock["present"]),
                    reserved=int(stock["reserved"]),
                )
            )
        return normalized


async def sync_stocks(
    session_factory: sessionmaker[Session],
    cabinet_id: int,
    source: StockCatalogSource,
) -> StockSyncResult:
    with session_factory.begin() as session:
        run = SyncRunRepository(session).start(cabinet_id, "ozon", "stocks")
        run_id = run.id
        product_ids = [product.product_id for product in ProductRepository(session).list_for_cabinet(cabinet_id)]

    try:
        stocks = await source.fetch(product_ids)
        with session_factory.begin() as session:
            rows = StockRepository(session).replace_for_products(cabinet_id, product_ids, stocks)
            run = session.get(SyncRun, run_id)
            if run is None:
                raise RuntimeError("Stock sync run was not found")
            SyncRunRepository(session).finish(run, status="success", rows_received=rows)
        return StockSyncResult(sync_run_id=run_id, rows_received=rows)
    except Exception as exc:
        with session_factory.begin() as session:
            run = session.get(SyncRun, run_id)
            if run is not None:
                SyncRunRepository(session).finish(run, status="failed", error_message=str(exc)[:2000])
        raise
