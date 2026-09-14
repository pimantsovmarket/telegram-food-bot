from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True, slots=True)
class Database:
    engine: Engine
    session_factory: sessionmaker[Session]

    def healthcheck(self) -> bool:
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def dispose(self) -> None:
        self.engine.dispose()


def create_database(database_url: str, *, echo: bool = False) -> Database:
    if not database_url:
        raise ValueError("DATABASE_URL is not configured")
    engine = create_engine(database_url, echo=echo, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return Database(engine=engine, session_factory=factory)
