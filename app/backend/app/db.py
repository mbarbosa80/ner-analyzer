"""Database session handling and schema creation.

SQLite for the MVP; the models are plain SQLAlchemy 2.0 so moving to
PostgreSQL/PostGIS is a URL change plus a migration, not a rewrite.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)

if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _rec):          # pragma: no cover - driver glue
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False,
                            class_=Session, future=True)


def init_db() -> dict:
    """Create the schema, then migrate V1 data forward. Idempotent.

    The migration runs on every start rather than as a separate command on
    purpose: a half-migrated database — new tables present, elements not yet
    linked to canonical NERs — is a state nothing downstream is written to
    handle, and the only reliable way to never be in it is to make opening the
    database and finishing the migration the same act.
    """
    from . import migrate

    return migrate.run(engine, SessionLocal)


def get_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
