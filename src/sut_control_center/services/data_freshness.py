from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.models import SyncRun


SOURCE_ENTITIES = {
    "stocks": "stocks",
    "sales": "postings",
    "returns": "returns",
    "finance": "finance_accruals",
}
SOURCE_LABELS = {
    "stocks": "Остатки",
    "sales": "Продажи",
    "returns": "Возвраты",
    "finance": "Финансы",
}


class FreshnessState(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    NEVER_SYNCED = "NEVER_SYNCED"


@dataclass(frozen=True, slots=True)
class SourceFreshness:
    source: str
    state: FreshnessState
    last_success_at: datetime | None
    age: timedelta | None
    failed_after_success: bool


@dataclass(frozen=True, slots=True)
class DataFreshnessReport:
    cabinet_id: int
    sources: tuple[SourceFreshness, ...]

    @property
    def requires_attention(self) -> bool:
        return any(
            item.state is not FreshnessState.FRESH or item.failed_after_success
            for item in self.sources
        )

    def get(self, source: str) -> SourceFreshness:
        return next(item for item in self.sources if item.source == source)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def calculate_data_freshness(
    session: Session,
    cabinet_id: int,
    stale_after_minutes: dict[str, int],
    *,
    now: datetime | None = None,
) -> DataFreshnessReport:
    if set(stale_after_minutes) != set(SOURCE_ENTITIES):
        raise ValueError("Freshness thresholds must cover stocks, sales, returns and finance")
    if any(value <= 0 for value in stale_after_minutes.values()):
        raise ValueError("Freshness thresholds must be positive")
    checked_at = _utc(now or datetime.now(timezone.utc))
    results = []
    for source, entity in SOURCE_ENTITIES.items():
        base_filter = (SyncRun.cabinet_id == cabinet_id, SyncRun.entity == entity)
        last_success = session.scalar(
            select(SyncRun)
            .where(*base_filter, SyncRun.status == "success", SyncRun.finished_at.is_not(None))
            .order_by(SyncRun.finished_at.desc(), SyncRun.id.desc())
            .limit(1)
        )
        latest = session.scalar(
            select(SyncRun).where(*base_filter).order_by(SyncRun.started_at.desc(), SyncRun.id.desc()).limit(1)
        )
        if last_success is None:
            results.append(
                SourceFreshness(
                    source=source,
                    state=FreshnessState.NEVER_SYNCED,
                    last_success_at=None,
                    age=None,
                    failed_after_success=latest is not None and latest.status == "failed",
                )
            )
            continue
        success_at = _utc(last_success.finished_at)
        age = max(checked_at - success_at, timedelta())
        state = (
            FreshnessState.STALE
            if age > timedelta(minutes=stale_after_minutes[source])
            else FreshnessState.FRESH
        )
        failed_after_success = bool(
            latest is not None
            and latest.status == "failed"
            and _utc(latest.started_at) > success_at
        )
        results.append(SourceFreshness(source, state, success_at, age, failed_after_success))
    return DataFreshnessReport(cabinet_id, tuple(results))


def format_age(age: timedelta) -> str:
    total_minutes = max(int(age.total_seconds() // 60), 0)
    if total_minutes < 1:
        return "менее минуты"
    days, remaining = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(remaining, 60)
    parts = []
    if days:
        parts.append(f"{days} д")
    if hours:
        parts.append(f"{hours} ч")
    if minutes and not days:
        parts.append(f"{minutes} мин")
    return " ".join(parts)


def format_freshness_warning(report: DataFreshnessReport) -> str:
    if not report.requires_attention:
        return ""
    lines = ["⚠️ Данные требуют внимания"]
    for item in report.sources:
        if item.state is FreshnessState.FRESH and not item.failed_after_success:
            continue
        label = SOURCE_LABELS[item.source]
        if item.state is FreshnessState.NEVER_SYNCED:
            detail = "ещё не обновлялись"
        else:
            detail = f"не обновлялись {format_age(item.age or timedelta())}"
        if item.failed_after_success:
            detail = f"последняя синхронизация завершилась ошибкой; {detail}"
        lines.append(f"• {label}: {detail}")
    return "\n".join(lines)
