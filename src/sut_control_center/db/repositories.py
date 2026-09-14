from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from .models import AppState, Cabinet, SyncRun, utc_now


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
