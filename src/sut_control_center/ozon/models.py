from dataclasses import dataclass
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
