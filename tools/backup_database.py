"""Create a consistent online backup of the AutoFB SQLite database."""
from __future__ import annotations

import argparse
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def backup_database(
    database_path: str | Path,
    backup_directory: str | Path,
    *,
    keep: int = 7,
    now: datetime | None = None,
) -> Path:
    """Back up a live SQLite database and retain the newest ``keep`` copies."""
    source = Path(database_path)
    if not source.is_file():
        raise FileNotFoundError(f"Database does not exist: {source}")
    if keep < 1:
        raise ValueError("keep must be at least 1")

    destination_directory = Path(backup_directory)
    destination_directory.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    destination = destination_directory / f"autofb-{timestamp:%Y%m%dT%H%M%SZ}.db"
    if destination.exists():
        raise FileExistsError(f"Backup already exists: {destination}")

    try:
        with closing(sqlite3.connect(source)) as source_connection:
            integrity = source_connection.execute("PRAGMA integrity_check").fetchone()
            if not integrity or integrity[0] != "ok":
                raise RuntimeError(f"Source database integrity check failed: {integrity}")
            with closing(sqlite3.connect(destination)) as destination_connection:
                source_connection.backup(destination_connection)
                destination_integrity = destination_connection.execute("PRAGMA integrity_check").fetchone()
                if not destination_integrity or destination_integrity[0] != "ok":
                    raise RuntimeError(f"Backup integrity check failed: {destination_integrity}")
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    backups = sorted(destination_directory.glob("autofb-????????T??????Z.db"), reverse=True)
    for expired_backup in backups[keep:]:
        expired_backup.unlink()
    return destination


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description="Create a consistent backup of the AutoFB SQLite database.")
    argument_parser.add_argument("--database", default=os.environ.get("AUTOFB_DATABASE_PATH", "autofb.db"))
    argument_parser.add_argument("--output", default=os.environ.get("AUTOFB_BACKUP_DIRECTORY", "backups"))
    argument_parser.add_argument("--keep", type=int, default=int(os.environ.get("AUTOFB_BACKUP_KEEP", "7")))
    return argument_parser


def main() -> int:
    args = parser().parse_args()
    destination = backup_database(args.database, args.output, keep=args.keep)
    print(f"Backup ready: {destination} ({destination.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
