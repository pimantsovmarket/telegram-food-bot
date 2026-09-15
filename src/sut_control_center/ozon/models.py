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
