from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..ozon.models import OzonPosting, OzonProduct, OzonStock
from .models import AppState, Cabinet, Posting, PostingItem, Product, Stock, SyncRun, utc_now


class CabinetRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, name: str, *, is_active: bool = True) -> Cabinet:
        cabinet = Cabinet(name=name, is_active=is_active)
        self.session.add(cabinet)
        self.session.flush()
        return cabinet

    def get(self, cabinet_id: int) -> Cabinet | None:
        return self.session.get(Cabinet, cabinet_id)


class SyncRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def start(self, cabinet_id: int, source: str, entity: str) -> SyncRun:
        run = SyncRun(cabinet_id=cabinet_id, source=source, entity=entity, status="running")
        self.session.add(run)
        self.session.flush()
        return run

    def finish(self, run: SyncRun, *, status: str, rows_received: int = 0, error_message: str | None = None, finished_at: datetime | None = None) -> SyncRun:
        run.status = status
        run.rows_received = rows_received
        run.error_message = error_message
        run.finished_at = finished_at or utc_now()
        self.session.flush()
        return run


class AppStateRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, key: str) -> Any:
        state = self.session.get(AppState, key)
        return None if state is None else state.value_json

    def set(self, key: str, value: Any) -> AppState:
        state = self.session.get(AppState, key)
        if state is None:
            state = AppState(key=key, value_json=value)
            self.session.add(state)
        else:
            state.value_json = value
            state.updated_at = utc_now()
        self.session.flush()
        return state


class ProductRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, cabinet_id: int, items: list[OzonProduct]) -> int:
        product_ids = [item.product_id for item in items]
        existing = {}
        if product_ids:
            statement = select(Product).where(
                Product.cabinet_id == cabinet_id,
                Product.product_id.in_(product_ids),
            )
            existing = {product.product_id: product for product in self.session.scalars(statement)}

        for item in items:
            product = existing.get(item.product_id)
            if product is None:
                product = Product(cabinet_id=cabinet_id, product_id=item.product_id)
                self.session.add(product)
            product.offer_id = item.offer_id
            product.name = item.name
            product.is_active = item.is_active
            product.updated_at = utc_now()
        self.session.flush()
        return len(items)

    def list_for_cabinet(self, cabinet_id: int) -> list[Product]:
        statement = select(Product).where(Product.cabinet_id == cabinet_id).order_by(Product.product_id)
        return list(self.session.scalars(statement))


class StockRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def replace_for_products(self, cabinet_id: int, product_ids: list[int], items: list[OzonStock]) -> int:
        if not product_ids:
            return 0
        statement = select(Stock).where(
            Stock.cabinet_id == cabinet_id,
            Stock.product_id.in_(product_ids),
        )
        existing = {
            (stock.product_id, stock.stock_type, stock.sku): stock
            for stock in self.session.scalars(statement)
        }
        received_keys = set()
        for item in items:
            key = (item.product_id, item.stock_type, item.sku)
            received_keys.add(key)
            stock = existing.get(key)
            if stock is None:
                stock = Stock(
                    cabinet_id=cabinet_id,
                    product_id=item.product_id,
                    stock_type=item.stock_type,
                    sku=item.sku,
                )
                self.session.add(stock)
            stock.offer_id = item.offer_id
            stock.present = item.present
            stock.reserved = item.reserved
            stock.updated_at = utc_now()

        stale_ids = [stock.id for key, stock in existing.items() if key not in received_keys]
        if stale_ids:
            self.session.execute(delete(Stock).where(Stock.id.in_(stale_ids)))
        self.session.flush()
        return len(items)

    def list_for_cabinet(self, cabinet_id: int) -> list[Stock]:
        statement = select(Stock).where(Stock.cabinet_id == cabinet_id).order_by(Stock.product_id, Stock.stock_type, Stock.sku)
        return list(self.session.scalars(statement))


class PostingRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(
        self,
        cabinet_id: int,
        postings: list[OzonPosting],
        product_by_offer: dict[str, int],
    ) -> tuple[int, int, int]:
        existing_postings = {
            (posting.scheme, posting.posting_number): posting
            for posting in self.session.scalars(select(Posting).where(Posting.cabinet_id == cabinet_id))
        }
        item_count = 0
        unmatched_count = 0
        for source_posting in postings:
            posting_key = (source_posting.scheme, source_posting.posting_number)
            posting = existing_postings.get(posting_key)
            if posting is None:
                posting = Posting(
                    cabinet_id=cabinet_id,
                    scheme=source_posting.scheme,
                    posting_number=source_posting.posting_number,
                )
                self.session.add(posting)
                existing_postings[posting_key] = posting
            posting.status = source_posting.status
            posting.event_at = datetime.fromisoformat(source_posting.event_at.replace("Z", "+00:00"))
            posting.updated_at = utc_now()
            self.session.flush()

            existing_items = {
                (item.offer_id, item.sku): item
                for item in self.session.scalars(select(PostingItem).where(PostingItem.posting_id == posting.id))
            }
            received_keys = set()
            for source_item in source_posting.items:
                item_key = (source_item.offer_id, source_item.sku)
                received_keys.add(item_key)
                item = existing_items.get(item_key)
                if item is None:
                    item = PostingItem(
                        posting_id=posting.id,
                        cabinet_id=cabinet_id,
                        offer_id=source_item.offer_id,
                        sku=source_item.sku,
                    )
                    self.session.add(item)
                    existing_items[item_key] = item
                product_id = product_by_offer.get(source_item.offer_id)
                item.product_id = product_id
                item.quantity = source_item.quantity
                item.match_status = "matched" if product_id is not None else "unmatched"
                item.match_error = None if product_id is not None else f"Unknown offer_id: {source_item.offer_id}"
                item.updated_at = utc_now()
                item_count += 1
                unmatched_count += int(product_id is None)

            stale_ids = [item.id for key, item in existing_items.items() if key not in received_keys]
            if stale_ids:
                self.session.execute(delete(PostingItem).where(PostingItem.id.in_(stale_ids)))
        self.session.flush()
        return len(postings), item_count, unmatched_count

    def list_for_cabinet(self, cabinet_id: int) -> list[Posting]:
        statement = select(Posting).where(Posting.cabinet_id == cabinet_id).order_by(Posting.event_at, Posting.id)
        return list(self.session.scalars(statement))
