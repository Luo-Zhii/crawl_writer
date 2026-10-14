"""Engine and session management.

SQLite today; the repository layer above this is what keeps a move to
Postgres from touching call sites.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import event, inspect
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


def upgrade_to_head() -> None:
    """Bring the database schema up to date.

    ``create_db_and_tables`` only creates tables that are missing; it never
    alters an existing one. So adding a column leaves an older database
    half-upgraded and every query touching that column fails at runtime.
    Since this is a single-user local app, running the migrations at startup
    is both safe and the only way the user never sees that state.
    """
    from alembic import command
    from alembic.config import Config

    settings = get_settings()
    settings.ensure_dirs()

    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.db_url)

    tables = set(inspect(get_engine()).get_table_names())
    if tables and "alembic_version" not in tables:
        # Schema built straight from the models (tests, and any database made
        # before migrations were tracked). Its shape already matches, so
        # record it as current instead of replaying migrations that would try
        # to create tables that exist.
        command.stamp(config, "head")
        return

    command.upgrade(config, "head")


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
