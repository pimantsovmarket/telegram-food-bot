from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from ..db.models import SyncRun
from ..db.repositories import ProductRepository, SyncRunRepository
from ..ozon.client import OzonClient
from ..ozon.errors import OzonResponseError
from ..ozon.models import OzonProduct


@dataclass(frozen=True, slots=True)
class ProductSyncResult:
    sync_run_id: int
    rows_received: int


class ProductCatalogSource:
    def __init__(self, client: OzonClient, *, page_size: int = 1000) -> None:
        self.client = client
        self.page_size = page_size

    async def fetch_all(self) -> list[OzonProduct]:
        products: dict[int, OzonProduct] = {}
        last_id = ""
        while True:
            response = await self.client.post(
                "/v3/product/list",
                json={"filter": {"visibility": "ALL"}, "last_id": last_id, "limit": self.page_size},
            )
            result = response.data.get("result")
            if not isinstance(result, dict) or not isinstance(result.get("items"), list):
                raise OzonResponseError("Ozon product list has an unexpected structure")
            items = result["items"]
            details = await self._fetch_details(items)
            products.update((product.product_id, product) for product in details)
            next_last_id = str(result.get("last_id") or "")
            if not items or not next_last_id or next_last_id == last_id:
                break
            last_id = next_last_id
        return list(products.values())

    async def _fetch_details(self, items: list[dict[str, Any]]) -> list[OzonProduct]:
        product_ids = [int(item["product_id"]) for item in items if isinstance(item, dict) and item.get("product_id") is not None]
        if not product_ids:
            return []
        response = await self.client.post("/v3/product/info/list", json={"product_id": product_ids})
        details = response.data.get("items")
        if not isinstance(details, list):
            raise OzonResponseError("Ozon product info list has an unexpected structure")
        normalized = []
        for item in details:
            if not isinstance(item, dict) or item.get("id") is None:
                continue
            normalized.append(
                OzonProduct(
                    product_id=int(item["id"]),
                    offer_id=str(item.get("offer_id") or ""),
                    name=str(item.get("name") or item.get("offer_id") or item["id"]),
                    is_active=not bool(item.get("is_archived") or item.get("is_autoarchived")),
                )
            )
        return normalized


async def sync_products(
    session_factory: sessionmaker[Session],
    cabinet_id: int,
    source: ProductCatalogSource,
) -> ProductSyncResult:
    with session_factory.begin() as session:
        run = SyncRunRepository(session).start(cabinet_id, "ozon", "products")
        run_id = run.id

    try:
        products = await source.fetch_all()
        with session_factory.begin() as session:
            rows = ProductRepository(session).upsert_many(cabinet_id, products)
            run = session.get(SyncRun, run_id)
            if run is None:
                raise RuntimeError("Product sync run was not found")
            SyncRunRepository(session).finish(run, status="success", rows_received=rows)
        return ProductSyncResult(sync_run_id=run_id, rows_received=rows)
    except Exception as exc:
        with session_factory.begin() as session:
            run = session.get(SyncRun, run_id)
            if run is not None:
                SyncRunRepository(session).finish(run, status="failed", error_message=str(exc)[:2000])
        raise
