"""SQLAlchemy engine/session setup (SQLite by default), migrations included."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()

# check_same_thread=False lets the SQLite connection be shared across FastAPI's
# threadpool workers; fine for a single-user local tool.
_connect_args = {"check_same_thread": False} if _settings.db_url.startswith("sqlite") else {}
engine = create_engine(_settings.db_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record) -> None:
    """WAL lets the API, the worker and backups read while one writes; the busy
    timeout makes a briefly locked database wait instead of erroring."""
    if not _settings.db_url.startswith("sqlite"):
        return
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=10000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


def init_db() -> None:
    # Import models so they register on Base.metadata before create_all.
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
    _run_migrations()


def _add_missing_columns() -> None:
    """Additive auto-migration: create_all makes new tables but never alters old ones.

    Missing columns are added as plain nullable columns (SQLite can't add NOT NULL
    without a constant default); the ORM still fills Python-side defaults on new
    rows. Renames, type changes and data fixes go in MIGRATIONS below.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in have:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'))


def _fail_orphaned_sends(conn: Connection) -> None:
    # Sends used to run as in-memory tasks; a restart left their rows "pending"
    # forever. Sends are durable tasks now, so these can never complete.
    for table in ("email_logs", "linkedin_logs"):
        conn.execute(
            text(
                f"UPDATE {table} SET status='failed', "
                "error='Interrupted by a restart before sends became durable tasks' "
                "WHERE status='pending'"
            )
        )


# Numbered, append-only data migrations. Never edit or reorder a shipped entry.
MIGRATIONS: list[tuple[int, str, Callable[[Connection], None]]] = [
    (1, "baseline", lambda conn: None),
    (2, "fail sends orphaned by the old in-memory background tasks", _fail_orphaned_sends),
]


def _run_migrations() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        done = {row[0] for row in conn.execute(text("SELECT version FROM schema_migrations"))}
        for version, name, fn in MIGRATIONS:
            if version in done:
                continue
            fn(conn)
            conn.execute(
                text("INSERT INTO schema_migrations (version, name) VALUES (:v, :n)"), {"v": version, "n": name}
            )


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
