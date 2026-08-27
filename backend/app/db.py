"""Database session handling and first-run seeding."""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .logging_setup import get_logger
from .models import Base

log = get_logger("db")

connect_args = {}
if settings.database_url.startswith("sqlite"):
    # FastAPI serves requests on a threadpool; SQLite needs to allow that.
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.database_url, connect_args=connect_args, pool_pre_ping=True, future=True
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False,
                            future=True)


def wait_for_database(timeout: float = 90.0) -> None:
    """Block until the database accepts a connection, or give up loudly.

    A container usually starts before the network around it is ready --
    Railway's private networking takes a few seconds, and a managed database
    may still be booting. Connecting immediately gets "connection refused" and
    the app crash-loops for a problem that would have resolved itself.

    Retrying also covers the ordinary case of the database restarting under a
    running app.
    """
    from sqlalchemy import text

    deadline = time.monotonic() + timeout
    attempt = 0
    while True:
        attempt += 1
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            if attempt > 1:
                log.info("Database reachable after %d attempt(s).", attempt)
            return
        except Exception as exc:  # noqa: BLE001 - any failure means "not yet"
            if time.monotonic() >= deadline:
                log.error("Database unreachable after %.0fs: %s", timeout, exc)
                raise
            wait = min(5.0, 0.5 * attempt)
            log.warning("Database not ready (attempt %d): %s -- retrying in %.1fs",
                        attempt, str(exc).splitlines()[0][:120], wait)
            time.sleep(wait)


def init_db() -> None:
    """Create tables, add any new columns, and seed the built-in niches."""
    wait_for_database()
    Base.metadata.create_all(engine)
    _add_missing_columns()

    from .niches import seed_builtin_niches

    with session_scope() as db:
        seed_builtin_niches(db)


def _add_missing_columns() -> None:
    """Add columns that exist in the models but not yet in the database.

    ``create_all`` only ever creates missing *tables*, so adding a field to a
    model leaves existing installs raising "no such column" on the next query.
    This closes that gap for the additive changes that make up almost every
    schema change here.

    It is deliberately narrow: it only ADDs nullable or defaulted columns and
    never drops, renames or retypes anything. Anything beyond that needs a real
    migration tool -- see the pre-launch list in the README.
    """
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        present = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue

            spec = column.type.compile(engine.dialect)
            default = column.default.arg if column.default is not None else None
            if callable(default):
                default = None

            clause = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {spec}'
            if default is not None and not isinstance(default, (list, dict)):
                literal = ("1" if default is True else "0" if default is False
                           else f"'{default}'" if isinstance(default, str)
                           else str(default))
                clause += f" DEFAULT {literal}"
            elif not column.nullable:
                # A NOT NULL column needs something for the existing rows.
                clause += " DEFAULT ''" if "CHAR" in spec.upper() or "TEXT" in spec.upper() else " DEFAULT 0"

            try:
                with engine.begin() as connection:
                    connection.execute(text(clause))
                log.info("Added column %s.%s", table.name, column.name)
            except Exception as exc:  # noqa: BLE001 - never block startup
                log.warning("Could not add %s.%s: %s", table.name, column.name, exc)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on error."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
