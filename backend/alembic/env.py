import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Add the backend directory to sys.path so we can import app modules
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import logging
from app.config import get_settings
from app.db import Base, FLOWSMITH_MIGRATION_LOCK_ID

logger = logging.getLogger("flowsmith.alembic")

# Import all models so Base.metadata knows about them
from app.models import (  # noqa: F401
    AuditEvent, Credential, DataTable, DataTableColumn, DataTableRow, Execution, ExecutionEvent, FileRecord, Job,
    OAuthState, Organization, OrganizationMember, Workspace,
    WorkspaceMember, WorkflowVersionRecord, WorkflowShare,
    WebhookTrigger, ScheduleTrigger, WebhookDelivery,
    User, WorkflowRecord, RagCollection, PasswordResetToken, WorkflowTest,
    Environment, UserAPIKey, WorkflowTemplate,
)

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Set the database URL from the app's config
settings = get_settings()
db_url = settings.database_url.strip() if settings.database_url else ""
config.set_main_option("sqlalchemy.url", db_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Add your model's MetaData object here
# for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode with PostgreSQL advisory locking."""
    import time

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        is_postgres = connection.dialect.name == "postgresql"
        lock_id = FLOWSMITH_MIGRATION_LOCK_ID
        acquired = False
        if is_postgres:
            from sqlalchemy import text
            try:
                connection.execute(text("SET lock_timeout = '60s'"))
            except Exception:
                pass

            # Attempt to acquire advisory lock with retry and orphan detection
            for attempt in range(1, 16):
                try:
                    res = connection.execute(text(f"SELECT pg_try_advisory_lock({lock_id})")).scalar()
                    if res:
                        acquired = True
                        logger.info("alembic: acquired PostgreSQL advisory lock (%s) for migration serialization", lock_id)
                        break
                except Exception as exc:
                    logger.warning("alembic: try_advisory_lock attempt %d error: %s", attempt, exc)

                logger.info("alembic: advisory lock (%s) held by another session; waiting (attempt %d/15)...", lock_id, attempt)
                time.sleep(1)

            if not acquired:
                logger.warning("alembic: advisory lock (%s) not acquired after 15s; inspecting holding session...", lock_id)
                try:
                    holder = connection.execute(text(f"""
                        SELECT l.pid, a.usename, a.state, a.backend_start, a.query
                        FROM pg_locks l
                        JOIN pg_stat_activity a ON l.pid = a.pid
                        WHERE l.locktype = 'advisory' AND l.objid = {lock_id}
                    """)).mappings().first()

                    if holder:
                        logger.warning(
                            "alembic: lock (%s) held by PID %s (state=%s, query=%s, start=%s)",
                            lock_id, holder.get("pid"), holder.get("state"), holder.get("query"), holder.get("backend_start")
                        )
                        if holder.get("state") in ("idle", "idle in transaction", "idle in transaction (aborted)"):
                            logger.warning("alembic: terminating orphaned/idle session PID %s holding advisory lock", holder.get("pid"))
                            connection.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": holder.get("pid")})
                            time.sleep(1)
                            res = connection.execute(text(f"SELECT pg_try_advisory_lock({lock_id})")).scalar()
                            if res:
                                acquired = True
                                logger.info("alembic: acquired PostgreSQL advisory lock (%s) after clearing orphaned session", lock_id)
                except Exception as exc:
                    logger.warning("alembic: could not inspect or terminate lock holder: %s", exc)

            if not acquired:
                # Fallback to direct blocking lock with log
                logger.warning("alembic: waiting on blocking pg_advisory_lock(%s)...", lock_id)
                connection.execute(text(f"SELECT pg_advisory_lock({lock_id})"))
                acquired = True
                logger.info("alembic: acquired PostgreSQL advisory lock (%s)", lock_id)

        try:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )

            with context.begin_transaction():
                context.run_migrations()
        finally:
            if is_postgres and acquired:
                from sqlalchemy import text
                try:
                    connection.execute(text(f"SELECT pg_advisory_unlock({lock_id})"))
                    logger.info("alembic: released PostgreSQL advisory lock (%s)", lock_id)
                except Exception as exc:
                    logger.warning("alembic: failed to release advisory lock (%s): %s", lock_id, exc)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
