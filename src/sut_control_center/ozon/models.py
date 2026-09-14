from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class OzonResponse:
    status_code: int
    data: dict[str, Any]
