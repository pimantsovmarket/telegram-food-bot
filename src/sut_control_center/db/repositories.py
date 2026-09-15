from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ozon.models import OzonProduct
from .models import AppState, Cabinet, Product, SyncRun, utc_now


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
