"""Standalone database migration runner (Phase 11 / Enterprise Stability).

Usage:
    python -m app.scripts.migrate [--check-only]

Can be used in deployment pipelines, Helm pre-upgrade hooks, and Docker Compose
to serialize schema migrations before starting application workers.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Ensure backend root is on sys.path regardless of current working directory
_backend_root = Path(__file__).resolve().parent.parent.parent
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

from app.db import _run_alembic_upgrade, engine, verify_schema_state, EXPECTED_ALEMBIC_HEAD

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("flowsmith.migrate")


def main() -> int:
    parser = argparse.ArgumentParser(description="Flowsmith Database Migration Runner")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Check schema revision and drift without applying migrations.",
    )
    args = parser.parse_args()

    logger.info("Inspecting database schema state...")
    state = verify_schema_state(engine)
    logger.info(
        "Current revision: %s | Expected head: %s | Status: %s | Missing tables: %s",
        state["current_revision"],
        EXPECTED_ALEMBIC_HEAD,
        state["status"],
        state["missing_tables"] or "None",
    )

    if args.check_only:
        if state["ok"]:
            logger.info("Schema state verified: at head revision with zero drift.")
            return 0
        else:
            logger.error("Schema drift or pending migration detected.")
            return 1

    if state["ok"]:
        logger.info("Database is already up-to-date at revision %s. Nothing to do.", state["current_revision"])
        return 0

    logger.info("Applying database migrations with advisory lock...")
    try:
        _run_alembic_upgrade()
        post_state = verify_schema_state(engine)
        if not post_state["ok"]:
            logger.error("Migration finished but schema verification failed: %s", post_state)
            return 1
        logger.info("Database migration successfully completed to revision %s.", post_state["current_revision"])
        return 0
    except Exception as exc:
        logger.exception("Migration failed with fatal error: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
