"""PostgreSQL database backup & restore CLI (pg_dump / psql) — Flowsmith DR utility.

Usage:
    python scripts/backup_db.py backup [--name NAME] [--out DIR] [--keep N]
    python scripts/backup_db.py restore --file PATH [--fresh]
    python scripts/backup_db.py list [--out DIR]
    python scripts/backup_db.py prune [--keep-days N] [--out DIR]

Defaults:
    --out       backups/
    --keep-days 14
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add backend to sys.path so app modules resolve cleanly
ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.utils.backup import (
    create_backup,
    restore_backup,
    list_backups,
    prune_backups,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Flowsmith PostgreSQL Backup & Restore CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Backup subcommand
    backup_parser = subparsers.add_parser("backup", help="Create a compressed .sql.gz database backup")
    backup_parser.add_argument("--name", default=None, help="Backup name (default: timestamped)")
    backup_parser.add_argument("--out", default=None, help="Output directory (default: backups/)")
    backup_parser.add_argument("--dsn", default=None, help="Database connection string (default: from config)")
    backup_parser.add_argument("--keep", type=int, default=14, help="Prune backups older than N days after backup")

    # Restore subcommand
    restore_parser = subparsers.add_parser("restore", help="Restore database from a .sql or .sql.gz dump")
    restore_parser.add_argument("--file", required=True, help="Path to the backup file to restore")
    restore_parser.add_argument("--dsn", default=None, help="Database connection string (default: from config)")
    restore_parser.add_argument("--fresh", action="store_true", help="Drop and recreate public schema before restore")

    # List subcommand
    list_parser = subparsers.add_parser("list", help="List available backups and sizes")
    list_parser.add_argument("--out", default=None, help="Backup directory (default: backups/)")

    # Prune subcommand
    prune_parser = subparsers.add_parser("prune", help="Delete backups older than retention window")
    prune_parser.add_argument("--keep-days", type=int, default=14, help="Number of days of backups to retain")
    prune_parser.add_argument("--out", default=None, help="Backup directory (default: backups/)")

    args = parser.parse_args()

    if args.command == "backup":
        filepath = create_backup(args.name, dsn=args.dsn, out_dir=args.out)
        print(f"[OK] Backup written: {filepath} ({round(filepath.stat().st_size / (1024*1024), 2)} MB)")
        if args.keep > 0:
            pruned = prune_backups(keep_days=args.keep, out_dir=args.out)
            if pruned:
                print(f"[INFO] Pruned {pruned} backup(s) older than {args.keep} days.")
    elif args.command == "restore":
        print(f"[INFO] Restoring backup from: {args.file} (fresh={args.fresh})")
        restore_backup(args.file, dsn=args.dsn, fresh=args.fresh)
        print(f"[OK] Successfully restored database from: {args.file}")
    elif args.command == "list":
        backups = list_backups(out_dir=args.out)
        if not backups:
            print("No backups found.")
        else:
            print(f"{'Name':<35} {'Size (MB)':<12} {'Created At'}")
            print("-" * 75)
            for b in backups:
                print(f"{b['filename']:<35} {b['size_mb']:<12} {b['created_at']}")
    elif args.command == "prune":
        removed = prune_backups(keep_days=args.keep_days, out_dir=args.out)
        print(f"[OK] Pruned {removed} backup(s) older than {args.keep_days} days.")


if __name__ == "__main__":
    main()

