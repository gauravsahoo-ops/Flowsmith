"""Database engine/session (SQLAlchemy 2.0). PostgreSQL-only.

The connection comes from ``config.py`` (``DATABASE_URL``). Tests point
the engine at a test database via ``init_db(url)`` before use.

Schema management (audit P0): development and tests bootstrap with
``create_all()`` (+ the legacy column patch). Production instead runs
Alembic migrations programmatically so deployed schema changes always
flow through reviewed migration files.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger("db")


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable WAL mode, foreign keys, and normal synchronous writes for SQLite.
    Optimizes test runner performance and eliminates database lock contention."""
    import sqlite3
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


def _engine_kwargs() -> dict:
    """Shared engine options (pool sizing from settings).

    Pool arguments are only valid for queue-pool style engines; SQLite
    (used by no product code) would reject ``pool_size``, so scope them
    to non-SQLite URLs defensively.
    """
    settings = get_settings()
    kwargs: dict = {}
    if not settings.database_url.lower().startswith("sqlite"):
        kwargs.update(
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_recycle=settings.db_pool_recycle_s,
            pool_pre_ping=settings.db_pool_pre_ping,
        )
    return kwargs


def _normalize_db_url(url: str) -> str:
    """Ensure a valid SQLAlchemy dialect driver is selected.
    If 'postgresql://' is specified without driver, prefer psycopg v3 if installed.
    """
    cleaned = url.strip()
    if cleaned.startswith("postgresql://"):
        try:
            import psycopg  # noqa: F401
            return "postgresql+psycopg://" + cleaned[len("postgresql://"):]
        except ImportError:
            pass
    return cleaned


def _redact_db_url(url: str) -> str:
    """Log-safe DSN: password masked out (never log credentials)."""
    import re

    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", url)


_DEFAULT_URL = _normalize_db_url(get_settings().database_url)
logger.debug("Using PostgreSQL database: %s", _redact_db_url(_DEFAULT_URL))
engine = create_engine(_DEFAULT_URL, **_engine_kwargs())
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _migrate_missing_columns() -> None:
    """Add columns introduced after an existing DB file was created.

    create_all() only creates missing tables, never missing columns; this
    keeps pre-existing dev databases working across milestones (M8 added
    executions.trace).
    """
    inspector = inspect(engine)
    # Only inspect tables that belong to this app's metadata (skip
    # runtime-managed pgvector tables which use the custom `vector` type
    # that SQLAlchemy's default inspector doesn't know).
    base_tables = set(Base.metadata.tables.keys())
    known = {}
    for t in inspector.get_table_names():
        if t not in base_tables:
            continue
        try:
            known[t] = {c["name"] for c in inspector.get_columns(t)}
        except Exception:
            continue
    # Iterate the plain table map instead of sorted_tables: the latter
    # warns about FK cycles (organizations/users/workspaces) it cannot
    # topologically order, which is irrelevant for a column-migration pass.
    for table in Base.metadata.tables.values():
        if table.name not in known:
            continue
        missing = [c for c in table.columns if c.name not in known[table.name]]
        if not missing:
            continue
        with engine.begin() as conn:
            for col in missing:
                if_not_exists = "IF NOT EXISTS " if engine.dialect.name == "postgresql" else ""
                ddl = f'ALTER TABLE "{table.name}" ADD COLUMN {if_not_exists}"{col.name}" {col.type.compile(engine.dialect)}'
                conn.execute(text(ddl))
        logger.warning("db: added missing columns %s to %s", [c.name for c in missing], table.name)


def _migrate_missing_indexes() -> None:
    """Ensure critical composite and lookup indexes exist on high-throughput tables.

    `Base.metadata.create_all()` creates missing tables but skips adding newly defined
    indexes on pre-existing tables. This idempotently builds missing performance indexes.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    critical_indexes = [
        # Executions (audit, listing, running check)
        ("executions", "ix_executions_workflow_started", 'CREATE INDEX IF NOT EXISTS ix_executions_workflow_started ON "executions" (workflow_id, started_at DESC)'),
        ("executions", "ix_executions_wf_status", 'CREATE INDEX IF NOT EXISTS ix_executions_wf_status ON "executions" (workflow_id, status)'),
        ("executions", "ix_executions_status_started", 'CREATE INDEX IF NOT EXISTS ix_executions_status_started ON "executions" (status, started_at DESC)'),
        ("executions", "ix_executions_user_started", 'CREATE INDEX IF NOT EXISTS ix_executions_user_started ON "executions" (user_id, started_at DESC)'),
        ("executions", "ix_executions_parent", 'CREATE INDEX IF NOT EXISTS ix_executions_parent ON "executions" (parent_execution_id)'),
        ("executions", "ix_executions_correlation", 'CREATE INDEX IF NOT EXISTS ix_executions_correlation ON "executions" (correlation_id)'),
        # Workflows (dashboard sort & filter)
        ("workflows", "ix_workflows_updated_at", 'CREATE INDEX IF NOT EXISTS ix_workflows_updated_at ON "workflows" (updated_at DESC)'),
        ("workflows", "ix_workflows_user_updated", 'CREATE INDEX IF NOT EXISTS ix_workflows_user_updated ON "workflows" (user_id, deleted_at, updated_at DESC)'),
        # Jobs (queue worker claim speed)
        ("jobs", "ix_jobs_claim", 'CREATE INDEX IF NOT EXISTS ix_jobs_claim ON "jobs" (status, next_retry_at, created_at, id)'),
    ]

    with engine.begin() as conn:
        for tbl, idx_name, ddl in critical_indexes:
            if tbl not in existing_tables:
                continue
            try:
                conn.execute(text(ddl))
            except Exception as e:
                logger.debug("Index creation %s skipped or error: %s", idx_name, e)


EXPECTED_ALEMBIC_HEAD: str = "b1d598391ba2"
FLOWSMITH_MIGRATION_LOCK_ID: int = 84729104
_migration_thread_lock = threading.Lock()


def get_engine() -> Engine:
    """Return the global SQLAlchemy Engine instance."""
    return engine


def get_current_revision(eng: Engine | None = None) -> str | None:
    """Read the active revision string from the alembic_version table, if present."""
    target_engine = eng or engine
    try:
        with target_engine.connect() as conn:
            inspector = inspect(conn)
            if not inspector.has_table("alembic_version"):
                return None
            val = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar()
            return str(val).strip() if val else None
    except Exception as exc:
        logger.debug("Could not read alembic_version: %s", exc)
        return None


def verify_schema_state(eng: Engine | None = None) -> dict[str, Any]:
    """Inspect and report database schema health, alembic revision, and drift."""
    target_engine = eng or engine
    current_rev = get_current_revision(target_engine)
    inspector = inspect(target_engine)
    existing_tables = set(inspector.get_table_names())
    expected_tables = {t for t in Base.metadata.tables if t != "alembic_version"}
    missing_tables = sorted(list(expected_tables - existing_tables))

    is_at_head = (current_rev == EXPECTED_ALEMBIC_HEAD)
    drift = len(missing_tables) > 0 or (current_rev is not None and not is_at_head)

    status = "ok" if (is_at_head and not missing_tables) else ("drift_detected" if drift else "unmigrated")
    return {
        "ok": not drift and is_at_head,
        "status": status,
        "current_revision": current_rev,
        "expected_revision": EXPECTED_ALEMBIC_HEAD,
        "missing_tables": missing_tables,
        "existing_table_count": len(existing_tables),
    }


def _run_alembic_upgrade() -> None:
    """Apply Alembic migrations up to head (production boot path).

    Synchronized via in-process lock and PostgreSQL advisory lock (FLOWSMITH_MIGRATION_LOCK_ID)
    to ensure multiple replicas or workers never race or run duplicate DDL.
    """
    from alembic import command
    from alembic.config import Config

    ini_path = Path(__file__).resolve().parents[1] / "alembic.ini"
    if not ini_path.is_file():  # packaged deployments without backend/
        raise RuntimeError(f"alembic.ini not found at {ini_path}; cannot migrate.")
    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))
    import app.models  # noqa: F401  (register all tables before compare)

    with _migration_thread_lock:
        is_postgres = engine.dialect.name == "postgresql"
        raw_conn = None
        if is_postgres:
            try:
                raw_conn = engine.connect()
                raw_conn.execute(text(f"SELECT pg_advisory_lock({FLOWSMITH_MIGRATION_LOCK_ID})"))
                logger.info("db: acquired PostgreSQL advisory lock for migration serialization")
            except Exception as e:
                logger.warning("db: could not acquire pg_advisory_lock (%s); proceeding with in-process lock", e)
                raw_conn = None

        try:
            # Check if database is already at expected head (idempotent skip)
            curr = get_current_revision(engine)
            if curr == EXPECTED_ALEMBIC_HEAD:
                logger.info("db: database schema is already at head revision %s; upgrade skipped", curr)
                return

            inspector = inspect(engine)
            has_version_table = inspector.has_table("alembic_version")
            if not has_version_table:
                known_tables = set(inspector.get_table_names())
                model_tables = {t for t in Base.metadata.tables if t != "alembic_version"}
                if model_tables and model_tables.issubset(known_tables):
                    command.stamp(cfg, "head")
                    logger.warning(
                        "db: pre-Alembic database adopted — stamped at head; "
                        "future changes flow through migrations only."
                    )
                    return
                # Fresh or partially-created database: run the full chain.
            command.upgrade(cfg, "head")
            logger.info("db: alembic upgrade head complete (revision=%s)", get_current_revision(engine))
        finally:
            if raw_conn is not None:
                try:
                    raw_conn.execute(text(f"SELECT pg_advisory_unlock({FLOWSMITH_MIGRATION_LOCK_ID})"))
                    logger.info("db: released PostgreSQL advisory lock")
                except Exception as e:
                    logger.debug("db: advisory unlock failed: %s", e)
                finally:
                    raw_conn.close()


def init_db(url: str | None = None) -> None:
    """Point the app at a different database (used by tests) and create schema."""
    global engine, SessionLocal
    if url:
        url = _normalize_db_url(url)
        old_engine = engine
        engine = create_engine(url, **_engine_kwargs())
        SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        try:
            old_engine.dispose()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass
    import app.models  # noqa: F401  (register all tables)

    settings = get_settings()
    if settings.app_env in ("production", "staging"):
        if settings.run_migrations_on_startup:
            # Deployed schema evolves through Alembic revisions safely serialized
            _run_alembic_upgrade()
            _migrate_missing_columns()
            _migrate_missing_indexes()
        else:
            state = verify_schema_state(engine)
            if not state["ok"]:
                raise RuntimeError(
                    f"Production startup blocked: database schema mismatch (current={state['current_revision']}, "
                    f"expected={EXPECTED_ALEMBIC_HEAD}, missing_tables={state['missing_tables']}). "
                    f"Run deployment migrations before starting workers."
                )
        return
    Base.metadata.create_all(bind=engine)
    _migrate_missing_columns()
    _migrate_missing_indexes()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: one session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session() -> Session:
    """Resolve the *current* sessionmaker at call time (background tasks
    must call this instead of importing SessionLocal, which would pin the
    engine created at module import)."""
    return SessionLocal()
