from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..ozon.models import OzonFinanceAccrual, OzonFinanceAccrualType, OzonPosting, OzonProduct, OzonReturn, OzonStock
from .models import (
    AppState,
    Cabinet,
    FinanceAccrual,
    FinanceAccrualComponent,
    FinanceAccrualItem,
    FinanceAccrualType,
    Posting,
    PostingItem,
    Product,
    ProductReplenishmentParameters,
    Return,
    Stock,
    SyncRun,
    utc_now,
)


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
            product.sku = item.sku
            product.size = item.size
            product.color = item.color
            product.is_active = item.is_active
            product.updated_at = utc_now()
        self.session.flush()
        return len(items)

    def list_for_cabinet(self, cabinet_id: int) -> list[Product]:
        statement = select(Product).where(Product.cabinet_id == cabinet_id).order_by(Product.product_id)
        return list(self.session.scalars(statement))


class ProductReplenishmentParametersRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    @staticmethod
    def _at(value: date | datetime) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        return datetime.combine(value, time.min, timezone.utc)

    def get_effective(
        self,
        cabinet_id: int,
        product_id: int,
        at: date | datetime,
    ) -> ProductReplenishmentParameters | None:
        moment = self._at(at)
        statement = (
            select(ProductReplenishmentParameters)
            .where(
                ProductReplenishmentParameters.cabinet_id == cabinet_id,
                ProductReplenishmentParameters.product_id == product_id,
                ProductReplenishmentParameters.effective_from <= moment,
                (
                    ProductReplenishmentParameters.effective_to.is_(None)
                    | (ProductReplenishmentParameters.effective_to > moment)
                ),
            )
            .order_by(ProductReplenishmentParameters.effective_from.desc())
        )
        return self.session.scalar(statement)

    def set_parameters(
        self,
        cabinet_id: int,
        product_id: int,
        lead_time_days: int,
        safety_stock_days: int,
        effective_from: date | datetime,
    ) -> ProductReplenishmentParameters:
        if lead_time_days < 0:
            raise ValueError("lead_time_days must be non-negative")
        if safety_stock_days < 0:
            raise ValueError("safety_stock_days must be non-negative")
        starts_at = self._at(effective_from)
        active_statement = (
            select(ProductReplenishmentParameters)
            .where(
                ProductReplenishmentParameters.cabinet_id == cabinet_id,
                ProductReplenishmentParameters.product_id == product_id,
                ProductReplenishmentParameters.effective_to.is_(None),
            )
            .with_for_update()
        )
        active = self.session.scalar(active_statement)
        if active is not None:
            active_start = active.effective_from
            if active_start.tzinfo is None:
                active_start = active_start.replace(tzinfo=timezone.utc)
            if starts_at <= active_start:
                raise ValueError("effective_from must be later than the active version")
            active.effective_to = starts_at
            self.session.flush()

        parameters = ProductReplenishmentParameters(
            cabinet_id=cabinet_id,
            product_id=product_id,
            lead_time_days=lead_time_days,
            safety_stock_days=safety_stock_days,
            effective_from=starts_at,
        )
        self.session.add(parameters)
        self.session.flush()
        return parameters


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


class FinanceAccrualTypeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, items: list[OzonFinanceAccrualType]) -> int:
        type_ids = [item.type_id for item in items]
        existing = {}
        if type_ids:
            existing = {
                item.type_id: item
                for item in self.session.scalars(
                    select(FinanceAccrualType).where(FinanceAccrualType.type_id.in_(type_ids))
                )
            }
        for source in items:
            item = existing.get(source.type_id)
            if item is None:
                item = FinanceAccrualType(type_id=source.type_id)
                self.session.add(item)
            item.name = source.name
            item.description = source.description
            item.updated_at = utc_now()
        self.session.flush()
        return len(items)


class FinanceAccrualRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, cabinet_id: int, items: list[OzonFinanceAccrual]) -> tuple[int, int, int]:
        accrual_ids = [item.accrual_id for item in items]
        existing = {}
        if accrual_ids:
            existing = {
                item.accrual_id: item
                for item in self.session.scalars(
                    select(FinanceAccrual).where(FinanceAccrual.accrual_id.in_(accrual_ids))
                )
            }
            self.session.execute(delete(FinanceAccrualItem).where(FinanceAccrualItem.accrual_id.in_(accrual_ids)))
            self.session.execute(delete(FinanceAccrualComponent).where(FinanceAccrualComponent.accrual_id.in_(accrual_ids)))

        item_count = 0
        component_count = 0
        for source in items:
            accrual = existing.get(source.accrual_id)
            if accrual is None:
                accrual = FinanceAccrual(accrual_id=source.accrual_id, cabinet_id=cabinet_id)
                self.session.add(accrual)
            elif accrual.cabinet_id != cabinet_id:
                raise ValueError("Finance accrual belongs to another cabinet")
            accrual.operation_date = source.operation_date
            accrual.category = source.category
            accrual.posting_number = source.posting_number
            accrual.total_amount = source.total_amount
            accrual.currency = source.currency
            accrual.updated_at = utc_now()
            self.session.flush()

            for source_item in source.items:
                self.session.add(
                    FinanceAccrualItem(
                        accrual_id=source.accrual_id,
                        sku=source_item.sku,
                        quantity=source_item.quantity,
                        seller_price=source_item.seller_price,
                        sale_price=source_item.sale_price,
                        sale_amount=source_item.sale_amount,
                        sale_commission=source_item.sale_commission,
                        commission=source_item.commission,
                        commission_ratio=source_item.commission_ratio,
                        coinvestment=source_item.coinvestment,
                        bonus=source_item.bonus,
                    )
                )
                item_count += 1
            for source_component in source.components:
                self.session.add(
                    FinanceAccrualComponent(
                        accrual_id=source.accrual_id,
                        sku=source_component.sku,
                        type_id=source_component.type_id,
                        amount=source_component.amount,
                        currency=source_component.currency,
                    )
                )
                component_count += 1
        self.session.flush()
        return len(items), item_count, component_count


class ReturnRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_many(self, cabinet_id: int, items: list[OzonReturn]) -> tuple[int, int]:
        return_ids = [item.return_id for item in items]
        existing = {}
        if return_ids:
            existing = {
                item.return_id: item
                for item in self.session.scalars(
                    select(Return).where(Return.cabinet_id == cabinet_id, Return.return_id.in_(return_ids))
                )
            }

        products = list(self.session.scalars(select(Product).where(Product.cabinet_id == cabinet_id)))
        sku_matches: dict[int, list[int]] = {}
        offer_matches: dict[str, list[int]] = {}
        for product in products:
            if product.sku is not None:
                sku_matches.setdefault(product.sku, []).append(product.product_id)
            offer_matches.setdefault(product.offer_id, []).append(product.product_id)

        linked = 0
        for source in items:
            item = existing.get(source.return_id)
            if item is None:
                item = Return(return_id=source.return_id, cabinet_id=cabinet_id)
                self.session.add(item)
            product_id = None
            if source.sku is not None and len(sku_matches.get(source.sku, [])) == 1:
                product_id = sku_matches[source.sku][0]
            elif source.offer_id is not None and len(offer_matches.get(source.offer_id, [])) == 1:
                product_id = offer_matches[source.offer_id][0]
            item.source_id = source.source_id
            item.schema = source.schema
            item.type = source.type
            item.order_id = source.order_id
            item.order_number = source.order_number
            item.posting_number = source.posting_number
            item.sku = source.sku
            item.offer_id = source.offer_id
            item.product_id = product_id
            item.quantity = source.quantity
            item.reason = source.reason
            item.status_id = source.status_id
            item.status_code = source.status_code
            item.status_name = source.status_name
            item.status_changed_at = source.status_changed_at
            item.return_date = source.return_date
            item.final_moment = source.final_moment
            item.updated_at = utc_now()
            linked += int(product_id is not None)
        self.session.flush()
        return len(items), linked
