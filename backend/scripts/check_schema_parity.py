"""Schema parity check: alembic migrations vs SQLAlchemy create_all.

Builds one schema from `alembic upgrade head` and another from
`Base.metadata.create_all`, then diffs tables, columns, and index names.
Any drift means the migration chain no longer matches what a fresh app
boot creates — release-blocking.

Usage (requires a reachable PostgreSQL; creates/drops two scratch DBs):
    python scripts/check_schema_parity.py
Exit code 0 = identical, 1 = drift, 2 = could not run.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import create_engine, inspect, text  # noqa: E402

from app.config import get_settings  # noqa: E402


def _scratch_url(base_url: str, name: str) -> tuple[str, str]:
    from sqlalchemy.engine import make_url

    u = make_url(base_url)
    host = "127.0.0.1" if (u.host or "") in ("localhost", "") else u.host
    db = f"{name}_schema_probe"
    url = u.set(host=host, database=db).render_as_string(hide_password=False)
    return url, db


def _create_drop_db(admin_url: str, db: str, create: bool) -> None:
    import psycopg2
    from sqlalchemy.engine import make_url

    u = make_url(admin_url)
    conn = psycopg2.connect(
        host=u.host if u.host not in ("localhost", "") else "127.0.0.1",
        port=u.port, user=u.username, password=u.password, dbname="postgres",
    )
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,))
            exists = cur.fetchone() is not None
            if exists and not create:
                cur.execute(f'DROP DATABASE "{db}"')
            elif create and not exists:
                cur.execute(f'CREATE DATABASE "{db}"')
    finally:
        conn.close()


def _introspect(url: str) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Return (columns_by_table, indexes_by_table).

    Indexes are compared by name; a model/migration pair that drifts on
    indexes (added to one side only) is release-blocking just like column
    drift — index-only changes are otherwise invisible to this gate.
    """
    engine = create_engine(url)
    insp = inspect(engine)
    cols: dict[str, set[str]] = {}
    idxs: dict[str, set[str]] = {}
    for table in sorted(insp.get_table_names()):
        cols[table] = {c["name"] for c in insp.get_columns(table)}
        names: set[str] = set()
        for i in insp.get_indexes(table):
            n = i.get("name")
            if n:
                names.add(n)
        idxs[table] = names
    engine.dispose()
    return cols, idxs


# Index variances must be empty: every prior entry was repaired
# (perf indexes declared in models; redundant files constraint dropped;
# rag constraint named). Add an entry here ONLY with reviewed justification
# in the comment — anything unlisted fails the gate.
INDEX_PARITY_KNOWN: set[tuple[str, str, str]] = set()


def main() -> int:
    base = get_settings().database_url
    alembic_url, alembic_db = _scratch_url(base, "alembic")
    all_url, all_db = _scratch_url(base, "createall")
    admin_url = base.rsplit("/", 1)[0]

    try:
        for db in (alembic_db, all_db):
            _create_drop_db(admin_url, db, create=True)

        env = {**__import__("os").environ, "DATABASE_URL": alembic_url}
        r = subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=BACKEND, env=env, capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(r.stdout[-2000:])
            print(r.stderr[-2000:])
            print("FAIL: alembic upgrade head did not succeed.")
            return 2

        # create_all side
        env2 = {**__import__("os").environ, "DATABASE_URL": all_url}
        r2 = subprocess.run(
            [sys.executable, "-c", "from app.db import init_db; init_db()"],
            cwd=BACKEND, env=env2, capture_output=True, text=True,
        )
        if r2.returncode != 0:
            print(r2.stderr[-2000:])
            print("FAIL: create_all did not succeed.")
            return 2

        mig, mig_idx = _introspect(alembic_url)
        cur, cur_idx = _introspect(all_url)

        problems = []
        for table in sorted(set(mig) | set(cur)):
            if table in ("alembic_version", "vector_collections"):
                continue
            if table not in mig:
                problems.append(f"table '{table}': missing from migrations")
            elif table not in cur:
                problems.append(f"table '{table}': extra in migrations")
            else:
                missing = cur[table] - mig[table]
                extra = mig[table] - cur[table]
                for c in sorted(missing):
                    problems.append(f"table '{table}': column '{c}' missing from migrations")
                for c in sorted(extra):
                    problems.append(f"table '{table}': column '{c}' extra in migrations")
                missing_idx = cur_idx.get(table, set()) - mig_idx.get(table, set())
                extra_idx = mig_idx.get(table, set()) - cur_idx.get(table, set())
                for i in sorted(missing_idx):
                    if (table, i, "missing") in INDEX_PARITY_KNOWN:
                        print(f"  (known index variance, tolerated: table '{table}' index '{i}' model-only)")
                    else:
                        problems.append(f"table '{table}': index '{i}' missing from migrations")
                for i in sorted(extra_idx):
                    if (table, i, "extra") in INDEX_PARITY_KNOWN:
                        print(f"  (known index variance, tolerated: table '{table}' index '{i}' migration-only)")
                    else:
                        problems.append(f"table '{table}': index '{i}' extra in migrations")

        if problems:
            print("SCHEMA DRIFT detected:")
            for p in problems:
                print(f"  - {p}")
            return 1
        print(f"OK: migrations match models ({len(mig)} tables).")
        return 0
    finally:
        for db in (alembic_db, all_db):
            try:
                _create_drop_db(admin_url, db, create=False)
            except Exception as exc:  # pragma: no cover
                print(f"warn: cleanup of {db} failed: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
