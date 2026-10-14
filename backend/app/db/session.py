"""Engine and session management.

SQLite today; the repository layer above this is what keeps a move to
Postgres from touching call sites.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app.core.settings import get_settings

_engine: Engine | None = None


def _configure_sqlite(engine: Engine) -> None:
    """Enable the pragmas SQLite needs to behave well for our workload."""

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # noqa: ANN001
        cursor = dbapi_conn.cursor()
        # ON DELETE CASCADE is off by default in SQLite.
        cursor.execute("PRAGMA foreign_keys=ON")
        # WAL lets the crawl worker write while the API reads.
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        settings.ensure_dirs()
        _engine = create_engine(
            settings.db_url,
            echo=False,
            # The worker and the request handlers share the engine across threads.
            connect_args={"check_same_thread": False, "timeout": 30},
        )
        _configure_sqlite(_engine)
    return _engine


def reset_engine() -> None:
    """Drop the cached engine. Used by tests that point at a temp data dir."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def create_db_and_tables(engine: Engine | None = None) -> None:
    """Create tables directly from the models.

    Alembic owns schema changes in normal use; this is for tests and for a
    first run on a fresh machine.
    """
    SQLModel.metadata.create_all(engine or get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session for background work and CLI commands."""
    session = Session(get_engine())
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with Session(get_engine()) as session:
        yield session
