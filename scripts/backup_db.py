"""Backup the SQLite database using the online backup API (safe while
the app is running — no downtime, no file locks).

Usage:
    python scripts/backup_db.py [--db PATH] [--out DIR] [--keep N]

Defaults:
    --db   backend/data/app.db (override with DATABASE_URL if needed)
    --out  backend/data/backups
    --keep 7 (oldest backups beyond this count are pruned)
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[1] / "backend" / "data" / "app.db"


def backup(db_path: Path, out_dir: Path, keep: int) -> Path:
    if not db_path.is_file():
        raise SystemExit(f"database not found: {db_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = out_dir / f"app-{stamp}.db"
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    # integrity spot check on the copy
    check = sqlite3.connect(target)
    try:
        row = check.execute("PRAGMA integrity_check").fetchone()
        if row != ("ok",):
            raise SystemExit(f"backup failed integrity check: {row!r}")
    finally:
        check.close()

    _prune(out_dir, keep)
    return target


def _prune(out_dir: Path, keep: int) -> None:
    pattern = re.compile(r"^app-\d{8}-\d{6}\.db$")
    backups = sorted(
        (p for p in out_dir.iterdir() if p.is_file() and pattern.match(p.name)),
        key=lambda p: p.name,
        reverse=True,
    )
    for old in backups[keep:]:
        old.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Online SQLite backup.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="path to the database file")
    parser.add_argument("--out", default=str(DEFAULT_DB.parent / "backups"), help="backup directory")
    parser.add_argument("--keep", type=int, default=7, help="number of backups to keep")
    args = parser.parse_args()
    target = backup(Path(args.db), Path(args.out), args.keep)
    print(f"backup written: {target}")
    print(f"backups kept: {[p.name for p in sorted(Path(args.out).glob('app-*.db'))]}")


if __name__ == "__main__":
    main()
