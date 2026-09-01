"""Database session handling and first-run seeding."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from typing import Iterator, List

from sqlalchemy import create_engine
from sqlalchemy import types as sa_types
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .logging_setup import get_logger
from .models import Base

log = get_logger("db")

#: Distinguishes "this column has no default" from "its default is None",
#: which are different questions wanting different answers.
_NO_DEFAULT = object()

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


def _python_default(column):
    """The model's Python-side default for a column, or _NO_DEFAULT.

    ``default=dict`` and ``default=list`` are callables and have to be called
    to be useful -- reading ``.arg`` hands back the *function*, which the
    first version of this then threw away and replaced with a guess.
    """
    if column.default is None:
        return _NO_DEFAULT
    value = getattr(column.default, "arg", _NO_DEFAULT)
    if value is _NO_DEFAULT:
        return _NO_DEFAULT
    if callable(value):
        # SQLAlchemy wraps a zero-argument default so it takes an execution
        # context, so ``dict`` arrives here as ``lambda ctx: dict()`` and
        # calling it bare raises TypeError. Missing that is not harmless: it
        # falls through to the by-type guess below, which would back-fill
        # jobs.tags -- a list -- with {} instead of [].
        for arguments in ((None,), ()):
            try:
                return value(*arguments)
            except TypeError:
                continue
        return _NO_DEFAULT
    return value


def _sql_literal(value, column) -> str:
    """`value` as a literal the column's own type will accept, or "".

    Typed off the column rather than off the Python value, because that is
    exactly where the previous version went wrong. It asked whether the
    compiled type string contained "CHAR" or "TEXT" and fell back to ``0`` for
    everything else. SQLite accepts 0 into a JSON column and the tests were on
    SQLite, so it looked correct. PostgreSQL says

        column "sourcing_report" is of type json
        but default expression is of type integer

    and the ALTER fails. The failure was logged at warning and startup carried
    on, so the first query against jobs was what actually brought the app
    down, with a traceback pointing at the render worker.
    """
    from sqlalchemy import Boolean, Integer, Numeric, String

    if isinstance(column.type, sa_types.JSON):
        return _quote(json.dumps(value))
    if isinstance(column.type, Boolean):
        # Never 1/0: PostgreSQL refuses an integer default on a boolean, and
        # every Boolean column in the models is NOT NULL with a default.
        return "TRUE" if value else "FALSE"
    if isinstance(column.type, (Integer, Numeric)):
        return str(value)
    if isinstance(column.type, String):
        return _quote(str(value))
    return ""


def _quote(text_value: str) -> str:
    """A single-quoted SQL string, with embedded quotes doubled."""
    return "'" + text_value.replace("'", "''") + "'"


def _backfill_default(column) -> str:
    """What the rows already in the table should get for a new column.

    A column the model marks NOT NULL needs *something*, or the existing rows
    have no value for it. An empty container, an empty string, zero or false
    covers every additive change this project has made. Anything else is left
    without a default rather than guessed at -- a wrong backfill is silent and
    permanent, where a failed ALTER is at least loud.
    """
    from sqlalchemy import Boolean, Integer, Numeric, String

    value = _python_default(column)
    if value is not _NO_DEFAULT:
        literal = _sql_literal(value, column)
        if literal:
            return literal
    if column.nullable:
        return ""
    if isinstance(column.type, sa_types.JSON):
        return _quote("{}")
    if isinstance(column.type, Boolean):
        return "FALSE"
    if isinstance(column.type, String):
        return _quote("")
    if isinstance(column.type, (Integer, Numeric)):
        return "0"
    return ""


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
    unresolved: List[str] = []

    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        present = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue

            spec = column.type.compile(engine.dialect)
            clause = (f'ALTER TABLE "{table.name}" '
                      f'ADD COLUMN "{column.name}" {spec}')
            literal = _backfill_default(column)
            if literal:
                clause += f" DEFAULT {literal}"

            try:
                with engine.begin() as connection:
                    connection.execute(text(clause))
                log.info("Added column %s.%s", table.name, column.name)
            except Exception as exc:  # noqa: BLE001 - never block startup
                unresolved.append(f"{table.name}.{column.name}")
                log.warning("Could not add %s.%s: %s -- SQL was: %s",
                            table.name, column.name, exc, clause)

    if unresolved:
        # Startup still continues, because one failed additive change is not
        # always fatal. But it is said at ERROR and by name, because the
        # alternative is what production actually did: a warning nobody read,
        # then a stack trace from whichever query touched the table first,
        # pointing at the render worker rather than at the schema.
        log.error(
            "Schema is behind the models and %d column(s) could not be "
            "added: %s. Queries against those tables will fail until this is "
            "resolved.", len(unresolved), ", ".join(unresolved))


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
