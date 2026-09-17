from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from ..db.models import SyncRun
from ..db.repositories import ReturnRepository, SyncRunRepository
from ..ozon.client import OzonClient
from ..ozon.errors import OzonResponseError
from ..ozon.models import OzonReturn


@dataclass(frozen=True, slots=True)
class ReturnSyncResult:
    sync_run_id: int
    fbo_received: int
    fbs_received: int
    total_saved: int
    product_id_linked: int


class ReturnSource:
    def __init__(self, client: OzonClient, *, page_size: int = 500) -> None:
        if not 1 <= page_size <= 500:
            raise ValueError("Return page_size must be between 1 and 500")
        self.client = client
        self.page_size = page_size

    async def fetch(
        self, period_start: date | None = None, period_end: date | None = None
    ) -> tuple[list[OzonReturn], int, int]:
        if (period_start is None) != (period_end is None):
            raise ValueError("Return sync period must include both start and end")
        if period_start is not None and period_end is not None and period_end < period_start:
            raise ValueError("Return sync period is invalid")
        fbo = await self._fetch_schema("FBO", period_start, period_end)
        fbs = await self._fetch_schema("FBS", period_start, period_end)
        merged = {item.return_id: item for item in (*fbo, *fbs)}
        return list(merged.values()), len(fbo), len(fbs)

    async def _fetch_schema(
        self, schema: str, period_start: date | None, period_end: date | None
    ) -> list[OzonReturn]:
        last_id = 0
        result: list[OzonReturn] = []
        while True:
            filters: dict[str, Any] = {"return_schema": schema}
            if period_start is not None and period_end is not None:
                filters["visual_status_change_moment"] = {
                    "time_from": datetime.combine(period_start, time.min, timezone.utc).isoformat().replace("+00:00", "Z"),
                    "time_to": datetime.combine(period_end, time.max, timezone.utc).isoformat().replace("+00:00", "Z"),
                }
            response = await self.client.post(
                "/v1/returns/list",
                json={"filter": filters, "limit": self.page_size, "last_id": last_id},
            )
            entries = response.data.get("returns")
            if not isinstance(entries, list):
                raise OzonResponseError("Ozon returns response has an unexpected structure")
            page = [self._normalize(entry) for entry in entries]
            result.extend(page)
            if not response.data.get("has_next"):
                break
            if not page:
                raise OzonResponseError("Ozon returns pagination returned an empty page")
            next_last_id = page[-1].return_id
            if next_last_id == last_id:
                raise OzonResponseError("Ozon returns pagination last_id is invalid")
            last_id = next_last_id
        return result

    @classmethod
    def _normalize(cls, entry: Any) -> OzonReturn:
        if not isinstance(entry, dict) or entry.get("id") is None:
            raise OzonResponseError("Ozon return entry has an unexpected structure")
        product = entry.get("product") if isinstance(entry.get("product"), dict) else {}
        logistic = entry.get("logistic") if isinstance(entry.get("logistic"), dict) else {}
        visual = entry.get("visual") if isinstance(entry.get("visual"), dict) else {}
        status = visual.get("status") if isinstance(visual.get("status"), dict) else {}
        return OzonReturn(
            return_id=int(entry["id"]),
            source_id=cls._optional_int(entry.get("source_id")),
            schema=str(entry.get("schema") or "UNKNOWN"),
            type=str(entry.get("type") or "UNKNOWN"),
            order_id=cls._optional_int(entry.get("order_id")),
            order_number=cls._optional_str(entry.get("order_number")),
            posting_number=cls._optional_str(entry.get("posting_number")),
            sku=cls._optional_int(product.get("sku")),
            offer_id=cls._optional_str(product.get("offer_id")),
            quantity=int(product.get("quantity") or 0),
            reason=cls._optional_str(entry.get("return_reason_name")),
            status_id=cls._optional_int(status.get("id")),
            status_code=cls._optional_str(status.get("sys_name")),
            status_name=cls._optional_str(status.get("display_name")),
            status_changed_at=cls._optional_datetime(visual.get("change_moment")),
            return_date=cls._optional_datetime(logistic.get("return_date")),
            final_moment=cls._optional_datetime(logistic.get("final_moment")),
        )

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        return None if value in (None, "") else int(value)

    @staticmethod
    def _optional_str(value: Any) -> str | None:
        return None if value in (None, "") else str(value)

    @staticmethod
    def _optional_datetime(value: Any) -> datetime | None:
        if value in (None, ""):
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise OzonResponseError("Ozon return date is invalid") from exc


async def sync_returns(
    session_factory: sessionmaker[Session],
    cabinet_id: int,
    source: ReturnSource,
    period_start: date | None = None,
    period_end: date | None = None,
) -> ReturnSyncResult:
    with session_factory.begin() as session:
        run = SyncRunRepository(session).start(cabinet_id, "ozon_returns", "returns")
        run_id = run.id
    try:
        items, fbo_received, fbs_received = await source.fetch(period_start, period_end)
        with session_factory.begin() as session:
            total_saved, linked = ReturnRepository(session).upsert_many(cabinet_id, items)
            run = session.get(SyncRun, run_id)
            if run is None:
                raise RuntimeError("Return sync run was not found")
            SyncRunRepository(session).finish(run, status="success", rows_received=total_saved)
        return ReturnSyncResult(run_id, fbo_received, fbs_received, total_saved, linked)
    except Exception as exc:
        with session_factory.begin() as session:
            run = session.get(SyncRun, run_id)
            if run is not None:
                SyncRunRepository(session).finish(run, status="failed", error_message=str(exc)[:2000])
        raise
