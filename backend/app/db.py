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
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

logger = logging.getLogger("db")


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


_DEFAULT_URL = get_settings().database_url.strip()
logger.debug("Using PostgreSQL database: %s", _DEFAULT_URL)
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


def _run_alembic_upgrade() -> None:
    """Apply Alembic migrations up to head (production boot path).

    Legacy deployments built with create_all (no ``alembic_version`` row)
    but already at the current model shape are ADOPTED by stamping head
    first — their schema is identical, so replaying the chain would try to
    recreate existing tables."""
    from alembic import command
    from alembic.config import Config

    ini_path = Path(__file__).resolve().parents[1] / "alembic.ini"
    if not ini_path.is_file():  # packaged deployments without backend/
        raise RuntimeError(f"alembic.ini not found at {ini_path}; cannot migrate.")
    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))
    import app.models  # noqa: F401  (register all tables before compare)

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
    logger.info("db: alembic upgrade head complete")


def init_db(url: str | None = None) -> None:
    """Point the app at a different database (used by tests) and create schema."""
    global engine, SessionLocal
    if url:
        url = url.strip()
        engine = create_engine(url, **_engine_kwargs())
        SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    import app.models  # noqa: F401  (register all tables)

    if get_settings().app_env == "production":
        # Deployed schema evolves through Alembic revisions
        _run_alembic_upgrade()
        _migrate_missing_columns()
        return
    Base.metadata.create_all(bind=engine)
    _migrate_missing_columns()


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
