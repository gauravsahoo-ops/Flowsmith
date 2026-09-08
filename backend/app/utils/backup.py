"""Backup & restore utility (pg_dump/psql) — Phase 33 DR foundation.

Transport modes for the Postgres client binaries:

- ``local``  — binaries on PATH (native installs / CI containers).
- ``docker`` — ``docker exec`` into the database container (the common
  dev/single-host deployment: the server runs in Docker, so do the
  clients). Auto-selected when local binaries are missing and Docker
  is reachable.

Both backup and restore STREAM (never load a dump fully into memory):
pg_dump stdout is compressed chunk-wise into ``.sql.gz``; restores are
decompressed chunk-wise into psql's stdin. No shell is ever spawned
(Phase 23/38 audit fix).

Everything is parameterizable by DSN/output dir so the disaster-recovery
drill can run against scratch databases without touching production.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

BACKUP_DIR = Path(os.getenv("MAT_BACKUP_DIR", "backups"))
_CHUNK = 1 << 20  # 1 MiB


def _get_pg_env(dsn: str | None = None) -> dict[str, str]:
    """Environment for local-mode clients, parsed from the DSN."""
    settings = get_settings()
    target = dsn or settings.database_url
    env = os.environ.copy()
    if "postgresql" in target:
        parsed = urllib.parse.urlparse(target)
        env["PGHOST"] = parsed.hostname or "localhost"
        env["PGPORT"] = str(parsed.port or 5432)
        env["PGUSER"] = parsed.username or ""
        env["PGPASSWORD"] = parsed.password or ""
        env["PGDATABASE"] = parsed.path.lstrip("/") or "automate"
    return env


def _dsn_parts(dsn: str | None = None) -> dict[str, str]:
    target = dsn or get_settings().database_url
    parsed = urllib.parse.urlparse(target)
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "",
        "password": parsed.password or "",
        "dbname": parsed.path.lstrip("/") or "automate",
    }


def _local_client_available(binary: str) -> bool:
    return shutil.which(binary) is not None


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(
        ["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        timeout=15,
    )
    return probe.returncode == 0


def _base_cmd(tool: str, dsn: str | None, *, stdin: bool = False) -> tuple[list[str], dict[str, str]]:
    """Command prefix + env for one pg tool invocation.

    Returns (argv_prefix, extra_env). ``stdin`` adds ``docker exec -i``
    so psql can read the dump from the host.
    """
    settings = get_settings()
    mode = getattr(settings, "pg_client_mode", "auto")
    parts = _dsn_parts(dsn)
    pg_args = [
        "-h", parts["host"] if mode != "docker" else "localhost",
        "-p", parts["port"],
        "-U", parts["user"] or "postgres",
    ]
    env: dict[str, str] = {"PGPASSWORD": parts["password"]}

    if mode == "local" or (
        mode == "auto" and _local_client_available(tool)
    ):
        return [tool, *pg_args], {**os.environ, **env}

    if mode == "docker" or mode == "auto":
        container = getattr(settings, "pg_docker_container", "") or "mat-postgres"
        prefix = ["docker", "exec"]
        if stdin:
            prefix.append("-i")
        if parts["password"]:
            prefix += ["-e", f"PGPASSWORD={parts['password']}"]
        return [*prefix, container, tool, *pg_args], dict(os.environ)

    raise RuntimeError(f"Unknown pg_client_mode '{mode}' (auto|local|docker).")


def _db_name(dsn: str | None) -> str:
    return _dsn_parts(dsn)["dbname"]


# ----------------------------------------------------------------------
# create / restore / prune
# ----------------------------------------------------------------------

def create_backup(
    name: str | None = None,
    *,
    dsn: str | None = None,
    out_dir: str | Path | None = None,
) -> Path:
    """Dump the database into ``<out_dir>/<name>.sql.gz`` (streamed).

    Returns the path to the backup file. Raises RuntimeError when
    pg_dump fails; FileNotFoundError when no client transport exists.
    """
    directory = Path(out_dir) if out_dir else BACKUP_DIR
    directory.mkdir(parents=True, exist_ok=True)
    if name is None:
        name = f"backup_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"

    filepath = directory / f"{name}.sql.gz"
    dbname = _db_name(dsn)
    base, env = _base_cmd("pg_dump", dsn)
    cmd = [*base, "-d", dbname, "--no-owner", "--no-privileges"]

    logger.info("Creating backup '%s' of database '%s'", filepath, dbname)
    try:
        import gzip

        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        assert proc.stdout is not None
        with gzip.open(filepath, "wb") as gz:
            shutil.copyfileobj(proc.stdout, gz, _CHUNK)
        proc.stdout.close()
        stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        code = proc.wait(timeout=300)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            "No pg_dump transport available (local binary or Docker). "
            f"Tried mode auto/local/docker: {exc}"
        ) from exc
    if code != 0:
        filepath.unlink(missing_ok=True)
        raise RuntimeError(f"pg_dump failed ({code}): {stderr[-500:]}")

    size_mb = filepath.stat().st_size / (1024 * 1024)
    logger.info("Backup created: %s (%.2f MB)", filepath, size_mb)
    return filepath


def restore_backup(
    filepath: str | Path, *, dsn: str | None = None, fresh: bool = False
) -> bool:
    """Restore a ``.sql``/``.sql.gz`` dump into the target database.

    Streams the (decompressed) dump into psql's stdin. Never spawns a
    shell (Phase 23/38). Returns True on success.

    ``fresh=True`` drops and recreates the ``public`` schema first —
    REQUIRED when recovering a damaged database: a plain re-restore
    cannot replace existing rows (primary-key conflicts are skipped in
    tolerant mode), so corrupted data would survive the "recovery".
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Backup file not found: {filepath}")

    logger.info("Restoring backup from: %s", filepath)
    dbname = _db_name(dsn)
    base, env = _base_cmd("psql", dsn, stdin=True)
    cmd = [*base, "-d", dbname, "-q", "-v", "ON_ERROR_STOP=0"]

    # Strictly BYTES end to end: dumps are utf-8 SQL produced by pg_dump;
    # decoding/re-encoding through the Windows locale (cp1252) corrupts
    # multibyte characters before they reach psql.
    #
    # We pump bytes through an explicit pipe instead of handing the file
    # handle to subprocess: on Windows, subprocess detects fileno() on
    # the (gzipped) handle and passes the RAW COMPRESSED file to the
    # child, bypassing Python-side decompression entirely.
    import shutil

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=env,
        )
        assert proc.stdin is not None
        if filepath.suffix == ".gz":
            import gzip

            opener: Any = lambda: gzip.open(filepath, "rb")  # noqa: E731
        else:
            opener = lambda: open(filepath, "rb")  # noqa: SIM115
        with opener() as dump_in:
            if fresh:
                proc.stdin.write(
                    b"DROP SCHEMA IF EXISTS public CASCADE; "
                    b"CREATE SCHEMA public;\n"
                )
            shutil.copyfileobj(dump_in, proc.stdin, _CHUNK)
        proc.stdin.close()
        stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
        code = proc.wait(timeout=600)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"No psql transport available: {exc}"
        ) from exc

    if code != 0:
        logger.error("Restore failed: %s", stderr)
        raise RuntimeError(f"Restore failed: {stderr[-500:]}")
    if stderr.strip():
        # Surface SQL-level problems even in tolerant mode.
        logger.warning("Restore completed with notices/errors: %s", stderr[-500:])

    logger.info("Backup restored successfully into '%s'.", dbname)
    return True


def list_backups(out_dir: str | Path | None = None) -> list[dict[str, Any]]:
    directory = Path(out_dir) if out_dir else BACKUP_DIR
    if not directory.exists():
        return []
    backups = []
    for f in sorted(directory.glob("*.sql*"), reverse=True):
        stat = f.stat()
        backups.append({
            "name": f.stem.replace(".sql", ""),
            "filename": f.name,
            "size_mb": round(stat.st_size / (1024 * 1024), 2),
            "created_at": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        })
    return backups


def prune_backups(keep_days: int = 14, out_dir: str | Path | None = None) -> int:
    """Delete backup files older than the retention window; returns count."""
    directory = Path(out_dir) if out_dir else BACKUP_DIR
    if not directory.exists():
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=keep_days)
    removed = 0
    for f in directory.glob("*.sql*"):
        if datetime.fromtimestamp(f.stat().st_mtime, UTC) < cutoff:
            f.unlink(missing_ok=True)
            removed += 1
    return removed
