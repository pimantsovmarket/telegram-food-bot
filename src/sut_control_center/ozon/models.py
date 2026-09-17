from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class OzonResponse:
    status_code: int
    data: dict[str, Any]


@dataclass(frozen=True, slots=True)
class OzonProduct:
    product_id: int
    offer_id: str
    name: str
    is_active: bool
    sku: int | None = None
    size: str | None = None
    color: str | None = None


@dataclass(frozen=True, slots=True)
class OzonStock:
    product_id: int
    offer_id: str
    stock_type: str
    sku: int
    present: int
    reserved: int


@dataclass(frozen=True, slots=True)
class OzonPostingItem:
    offer_id: str
    sku: int
    quantity: int


@dataclass(frozen=True, slots=True)
class OzonPosting:
    posting_number: str
    scheme: str
    status: str
    event_at: str
    items: tuple[OzonPostingItem, ...]


@dataclass(frozen=True, slots=True)
class OzonFinanceAccrualType:
    type_id: int
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class OzonFinanceAccrualItem:
    sku: int | None
    quantity: int
    seller_price: Decimal | None = None
    sale_price: Decimal | None = None
    sale_amount: Decimal | None = None
    sale_commission: Decimal | None = None
    commission: Decimal | None = None
    commission_ratio: Decimal | None = None
    coinvestment: Decimal | None = None
    bonus: Decimal | None = None


@dataclass(frozen=True, slots=True)
class OzonFinanceAccrualComponent:
    sku: int | None
    type_id: int
    amount: Decimal
    currency: str


@dataclass(frozen=True, slots=True)
class OzonFinanceAccrual:
    accrual_id: int
    operation_date: date
    category: str
    posting_number: str | None
    total_amount: Decimal
    currency: str
    items: tuple[OzonFinanceAccrualItem, ...]
    components: tuple[OzonFinanceAccrualComponent, ...]


@dataclass(frozen=True, slots=True)
class OzonReturn:
    return_id: int
    source_id: int | None
    schema: str
    type: str
    order_id: int | None
    order_number: str | None
    posting_number: str | None
    sku: int | None
    offer_id: str | None
    quantity: int
    reason: str | None
    status_id: int | None
    status_code: str | None
    status_name: str | None
    status_changed_at: datetime | None
    return_date: datetime | None
    final_moment: datetime | None
