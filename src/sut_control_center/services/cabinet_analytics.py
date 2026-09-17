from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..db.models import (
    FinanceAccrual,
    FinanceAccrualComponent,
    FinanceAccrualItem,
    FinanceAccrualType,
    Posting,
    PostingItem,
    Product,
    Return,
    Stock,
)


ZERO = Decimal("0")

LOGISTICS_TYPES = {
    "CrossDock",
    "CrossDockPickUpCourierDelivery",
    "Drop-Off",
    "Drop-Off Agent",
    "LastMile",
    "LastMileCourier",
    "LastMilePickUpPoint",
    "Logistic",
    "Pick-Up",
    "PickUpCourierArrangement",
    "PickUpCourierDelivery",
    "Shipment",
    "SupplyInbound",
    "CourierPickUpByOzon",
    "CourierPickUpReinvoice",
    "DeliveryToHandoverPlaceByOzon",
    "InternationalLogisticDelta",
    "OzonGlobalLogisticsDelivery",
    "RfbsDomesticDelivery",
    "RfbsGlobalDelivery",
    "B2CLogistics",
    "B2CDeliveryToHandoverPlaceByOzon",
}
RETURN_LOGISTICS_TYPES = {
    "BackwardShipment",
    "ClientReturn",
    "PartialReturn",
    "PreparingToReturn",
    "ReturnFlowLogistic",
    "SellerReturns",
    "PickUpPointReturnAcceptance",
    "RfbsEasyReturn",
    "B2CBackwardLogistics",
    "B2CPickUpPointReturnAcceptance",
}
STORAGE_TYPES = {
    "Fulfillment",
    "Placements",
    "ReturnStorageInTheWarehouse",
    "TemporaryPlacement",
    "B2CTemporaryPlacement",
}


@dataclass(frozen=True, slots=True)
class ProductCabinetAnalytics:
    product_id: int
    sku: int | None
    delivered_units: int
    cancelled_units: int
    return_units: int
    current_stock: int


@dataclass(frozen=True, slots=True)
class CabinetAnalytics:
    period_start: date
    period_end: date
    delivered_units: int
    cancelled_units: int
    client_return_units: int
    full_return_units: int
    current_stock: int
    finance_accrual_total: Decimal
    sales_amount: Decimal
    commissions: Decimal
    logistics: Decimal
    return_logistics: Decimal
    storage: Decimal
    other_services: Decimal
    product_breakdown: tuple[ProductCabinetAnalytics, ...]
    unlinked_returns: int


def _decimal(value: Decimal | None) -> Decimal:
    return value if value is not None else ZERO


def calculate_cabinet_analytics(
    session: Session,
    cabinet_id: int,
    period_start: date,
    period_end: date,
) -> CabinetAnalytics:
    if period_end < period_start:
        raise ValueError("Cabinet analytics period is invalid")
    start_at = datetime.combine(period_start, time.min, timezone.utc)
    end_at = datetime.combine(period_end + timedelta(days=1), time.min, timezone.utc)

    posting_rows = session.execute(
        select(
            PostingItem.product_id,
            Posting.status,
            func.sum(PostingItem.quantity),
        )
        .join(Posting, Posting.id == PostingItem.posting_id)
        .where(
            Posting.cabinet_id == cabinet_id,
            Posting.event_at >= start_at,
            Posting.event_at < end_at,
            Posting.status.in_(("delivered", "cancelled")),
        )
        .group_by(PostingItem.product_id, Posting.status)
    )
    delivered_by_product: dict[int, int] = {}
    cancelled_by_product: dict[int, int] = {}
    delivered_units = 0
    cancelled_units = 0
    for product_id, status, quantity in posting_rows:
        units = int(quantity or 0)
        if status == "delivered":
            delivered_units += units
            if product_id is not None:
                delivered_by_product[int(product_id)] = delivered_by_product.get(int(product_id), 0) + units
        else:
            cancelled_units += units
            if product_id is not None:
                cancelled_by_product[int(product_id)] = cancelled_by_product.get(int(product_id), 0) + units

    return_moment = func.coalesce(Return.return_date, Return.status_changed_at)
    return_rows = session.execute(
        select(Return.product_id, Return.type, func.sum(Return.quantity))
        .where(
            Return.cabinet_id == cabinet_id,
            return_moment >= start_at,
            return_moment < end_at,
            Return.type.in_(("ClientReturn", "FullReturn")),
        )
        .group_by(Return.product_id, Return.type)
    )
    returns_by_product: dict[int, int] = {}
    client_return_units = 0
    full_return_units = 0
    unlinked_returns = 0
    for product_id, return_type, quantity in return_rows:
        units = int(quantity or 0)
        if return_type == "ClientReturn":
            client_return_units += units
        else:
            full_return_units += units
        if product_id is None:
            unlinked_returns += units
        else:
            returns_by_product[int(product_id)] = returns_by_product.get(int(product_id), 0) + units

    available_stock = case((Stock.present > Stock.reserved, Stock.present - Stock.reserved), else_=0)
    stock_by_product = {
        int(product_id): int(quantity or 0)
        for product_id, quantity in session.execute(
            select(Stock.product_id, func.sum(available_stock))
            .where(Stock.cabinet_id == cabinet_id)
            .group_by(Stock.product_id)
        )
    }

    finance_filter = (
        FinanceAccrual.cabinet_id == cabinet_id,
        FinanceAccrual.operation_date >= period_start,
        FinanceAccrual.operation_date <= period_end,
    )
    finance_accrual_total = _decimal(
        session.scalar(select(func.sum(FinanceAccrual.total_amount)).where(*finance_filter))
    )
    sales_amount, commissions = session.execute(
        select(func.sum(FinanceAccrualItem.sale_amount), func.sum(FinanceAccrualItem.commission))
        .join(FinanceAccrual, FinanceAccrual.accrual_id == FinanceAccrualItem.accrual_id)
        .where(*finance_filter)
    ).one()

    component_totals = {"logistics": ZERO, "return_logistics": ZERO, "storage": ZERO, "other": ZERO}
    components = session.execute(
        select(FinanceAccrualType.name, FinanceAccrualComponent.amount)
        .join(FinanceAccrual, FinanceAccrual.accrual_id == FinanceAccrualComponent.accrual_id)
        .outerjoin(FinanceAccrualType, FinanceAccrualType.type_id == FinanceAccrualComponent.type_id)
        .where(*finance_filter)
    )
    for type_name, amount in components:
        if type_name in RETURN_LOGISTICS_TYPES:
            bucket = "return_logistics"
        elif type_name in LOGISTICS_TYPES:
            bucket = "logistics"
        elif type_name in STORAGE_TYPES:
            bucket = "storage"
        else:
            bucket = "other"
        component_totals[bucket] += _decimal(amount)

    products = session.execute(
        select(Product.product_id, Product.sku)
        .where(Product.cabinet_id == cabinet_id)
        .order_by(Product.product_id)
    )
    breakdown = tuple(
        ProductCabinetAnalytics(
            product_id=int(product_id),
            sku=sku,
            delivered_units=delivered_by_product.get(int(product_id), 0),
            cancelled_units=cancelled_by_product.get(int(product_id), 0),
            return_units=returns_by_product.get(int(product_id), 0),
            current_stock=stock_by_product.get(int(product_id), 0),
        )
        for product_id, sku in products
    )

    return CabinetAnalytics(
        period_start=period_start,
        period_end=period_end,
        delivered_units=delivered_units,
        cancelled_units=cancelled_units,
        client_return_units=client_return_units,
        full_return_units=full_return_units,
        current_stock=sum(stock_by_product.values()),
        finance_accrual_total=finance_accrual_total,
        sales_amount=_decimal(sales_amount),
        commissions=_decimal(commissions),
        logistics=component_totals["logistics"],
        return_logistics=component_totals["return_logistics"],
        storage=component_totals["storage"],
        other_services=component_totals["other"],
        product_breakdown=breakdown,
        unlinked_returns=unlinked_returns,
    )
