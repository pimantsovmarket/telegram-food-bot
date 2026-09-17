from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from ..db.models import SyncRun
from ..db.repositories import FinanceAccrualRepository, FinanceAccrualTypeRepository, SyncRunRepository
from ..ozon.client import OzonClient
from ..ozon.errors import OzonResponseError
from ..ozon.models import (
    OzonFinanceAccrual,
    OzonFinanceAccrualComponent,
    OzonFinanceAccrualItem,
    OzonFinanceAccrualType,
)


@dataclass(frozen=True, slots=True)
class FinanceAccrualSyncResult:
    sync_run_id: int
    types_saved: int
    accruals_saved: int
    items_saved: int
    components_saved: int
    unknown_type_ids: tuple[int, ...]


class FinanceAccrualSource:
    def __init__(self, client: OzonClient) -> None:
        self.client = client

    async def fetch_types(self) -> list[OzonFinanceAccrualType]:
        response = await self.client.post("/v1/finance/accrual/types", json={})
        entries = response.data.get("accrual_types")
        if not isinstance(entries, list):
            raise OzonResponseError("Ozon finance accrual types response has an unexpected structure")
        result = []
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("id") is None:
                raise OzonResponseError("Ozon finance accrual type has an unexpected structure")
            result.append(
                OzonFinanceAccrualType(
                    type_id=int(entry["id"]),
                    name=str(entry.get("name") or ""),
                    description=str(entry.get("description") or ""),
                )
            )
        return result

    async def fetch_period(self, period_start: date, period_end: date) -> list[OzonFinanceAccrual]:
        if period_end < period_start:
            raise ValueError("Finance accrual sync period is invalid")
        result: dict[int, OzonFinanceAccrual] = {}
        current = period_start
        while current <= period_end:
            last_id = ""
            while True:
                response = await self.client.post(
                    "/v1/finance/accrual/by-day",
                    json={"date": current.isoformat(), "last_id": last_id},
                )
                entries = response.data.get("accruals")
                if not isinstance(entries, list):
                    raise OzonResponseError("Ozon finance accrual response has an unexpected structure")
                for entry in entries:
                    accrual = self._normalize_accrual(entry)
                    result[accrual.accrual_id] = accrual
                next_last_id = str(response.data.get("last_id") or "")
                if not next_last_id:
                    break
                if next_last_id == last_id:
                    raise OzonResponseError("Ozon finance accrual pagination cursor is invalid")
                last_id = next_last_id
            current += timedelta(days=1)
        return list(result.values())

    @classmethod
    def _normalize_accrual(cls, entry: Any) -> OzonFinanceAccrual:
        if not isinstance(entry, dict) or entry.get("accrual_id") is None or not entry.get("date"):
            raise OzonResponseError("Ozon finance accrual entry has an unexpected structure")
        total_amount, currency = cls._money(entry.get("total_amount"), required=True)
        posting_number = entry.get("unit_number")
        items = []
        components = []
        posting = entry.get("posting")
        if isinstance(posting, dict):
            products = posting.get("products")
            if products is not None and not isinstance(products, list):
                raise OzonResponseError("Ozon finance posting products have an unexpected structure")
            for product in products or []:
                if not isinstance(product, dict):
                    raise OzonResponseError("Ozon finance posting product has an unexpected structure")
                sku = cls._optional_int(product.get("sku"))
                commission = product.get("commission") if isinstance(product.get("commission"), dict) else {}
                items.append(
                    OzonFinanceAccrualItem(
                        sku=sku,
                        quantity=int(product.get("quantity") or 0),
                        seller_price=cls._decimal(commission.get("seller_price")),
                        sale_price=cls._decimal(commission.get("sale_price")),
                        sale_amount=cls._decimal(commission.get("sale_amount")),
                        sale_commission=cls._decimal(commission.get("sale_commission")),
                        commission=cls._decimal(commission.get("commission")),
                        commission_ratio=cls._decimal(commission.get("commission_ratio")),
                        coinvestment=cls._decimal(commission.get("coinvestment")),
                        bonus=cls._decimal(commission.get("bonus")),
                    )
                )
                delivery = product.get("delivery")
                if isinstance(delivery, dict):
                    components.extend(cls._components(delivery.get("services"), sku))

        components.extend(cls._components(entry.get("item_fees"), None))
        components.extend(cls._components(entry.get("container_fees"), None))
        non_item_fee = entry.get("non_item_fee")
        if isinstance(non_item_fee, dict):
            component = cls._component(non_item_fee, None)
            if component is not None:
                components.append(component)

        try:
            operation_date = date.fromisoformat(str(entry["date"])[:10])
        except ValueError as exc:
            raise OzonResponseError("Ozon finance accrual date is invalid") from exc
        return OzonFinanceAccrual(
            accrual_id=int(entry["accrual_id"]),
            operation_date=operation_date,
            category=str(entry.get("accrued_category") or "UNKNOWN"),
            posting_number=str(posting_number) if posting_number not in (None, "") else None,
            total_amount=total_amount,
            currency=currency,
            items=tuple(items),
            components=tuple(components),
        )

    @classmethod
    def _components(cls, entries: Any, default_sku: int | None) -> list[OzonFinanceAccrualComponent]:
        if entries is None:
            return []
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list):
            raise OzonResponseError("Ozon finance accrual components have an unexpected structure")
        result = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise OzonResponseError("Ozon finance accrual component has an unexpected structure")
            sku = cls._optional_int(entry.get("sku")) if entry.get("sku") is not None else default_sku
            component = cls._component(entry, sku)
            if component is not None:
                result.append(component)
            for nested_key in ("services", "fees"):
                if entry.get(nested_key) is not None:
                    result.extend(cls._components(entry[nested_key], sku))
        return result

    @classmethod
    def _component(cls, entry: dict[str, Any], sku: int | None) -> OzonFinanceAccrualComponent | None:
        if entry.get("type_id") is None:
            return None
        amount, currency = cls._money(entry.get("accrued") or entry.get("amount"), required=True)
        return OzonFinanceAccrualComponent(
            sku=sku,
            type_id=int(entry["type_id"]),
            amount=amount,
            currency=currency,
        )

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        return None if value in (None, "") else int(value)

    @classmethod
    def _money(cls, value: Any, *, required: bool = False) -> tuple[Decimal, str]:
        if isinstance(value, dict):
            amount = cls._decimal(value.get("amount") if "amount" in value else value.get("value"))
            currency = str(value.get("currency") or value.get("currency_code") or "RUB")
        else:
            amount = cls._decimal(value)
            currency = "RUB"
        if amount is None:
            if required:
                raise OzonResponseError("Ozon finance money value has an unexpected structure")
            amount = Decimal("0")
        return amount, currency

    @staticmethod
    def _decimal(value: Any) -> Decimal | None:
        if value is None:
            return None
        if isinstance(value, dict):
            value = value.get("amount") if "amount" in value else value.get("value")
        if value in (None, ""):
            return None
        text = str(value).strip()
        match = re.fullmatch(r'value:\s*"([+-]?\d+(?:\.\d+)?)"', text)
        if match:
            text = match.group(1)
        try:
            return Decimal(text)
        except InvalidOperation as exc:
            raise OzonResponseError("Ozon finance decimal value is invalid") from exc


async def sync_finance_accruals(
    session_factory: sessionmaker[Session],
    cabinet_id: int,
    source: FinanceAccrualSource,
    period_start: date,
    period_end: date,
) -> FinanceAccrualSyncResult:
    if period_end < period_start:
        raise ValueError("Finance accrual sync period is invalid")
    with session_factory.begin() as session:
        run = SyncRunRepository(session).start(cabinet_id, "ozon_finance", "finance_accruals")
        run_id = run.id
    try:
        types = await source.fetch_types()
        accruals = await source.fetch_period(period_start, period_end)
        known_type_ids = {item.type_id for item in types}
        observed_type_ids = {component.type_id for accrual in accruals for component in accrual.components}
        unknown_type_ids = tuple(sorted(observed_type_ids - known_type_ids))
        with session_factory.begin() as session:
            types_saved = FinanceAccrualTypeRepository(session).upsert_many(types)
            accruals_saved, items_saved, components_saved = FinanceAccrualRepository(session).upsert_many(
                cabinet_id,
                accruals,
            )
            run = session.get(SyncRun, run_id)
            if run is None:
                raise RuntimeError("Finance accrual sync run was not found")
            SyncRunRepository(session).finish(run, status="success", rows_received=accruals_saved)
        return FinanceAccrualSyncResult(
            sync_run_id=run_id,
            types_saved=types_saved,
            accruals_saved=accruals_saved,
            items_saved=items_saved,
            components_saved=components_saved,
            unknown_type_ids=unknown_type_ids,
        )
    except Exception as exc:
        with session_factory.begin() as session:
            run = session.get(SyncRun, run_id)
            if run is not None:
                SyncRunRepository(session).finish(run, status="failed", error_message=str(exc)[:2000])
        raise
