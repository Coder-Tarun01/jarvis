"""SQLAlchemy engine / session plumbing (SQLite by default)."""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()
settings.ensure_dirs()


class Base(DeclarativeBase):
    """Declarative base for every JARVIS table."""


_connect_args = {"check_same_thread": False, "timeout": 30} if settings.is_sqlite else {}

engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_pre_ping=True,
    connect_args=_connect_args,
)


if settings.is_sqlite:

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _record) -> None:  # pragma: no cover
        cursor = dbapi_connection.cursor()
        try:
            # WAL is the right default on a local disk. On some bind-mounted
            # filesystems (e.g. Windows drives shared into Docker) it is not
            # supported, so fall back to the rollback journal instead of
            # failing every connection.
            cursor.execute("PRAGMA journal_mode=WAL")
        except Exception:  # noqa: BLE001 - pragma support is filesystem dependent
            try:
                cursor.execute("PRAGMA journal_mode=DELETE")
            except Exception:  # noqa: BLE001
                pass
        try:
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
        except Exception:  # noqa: BLE001
            pass
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


def init_db() -> None:
    """Create tables. Safe to call on every boot."""
    from . import models  # noqa: F401  — registers the mappers

    Base.metadata.create_all(bind=engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
